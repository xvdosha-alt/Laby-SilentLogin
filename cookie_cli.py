#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import browser_cookie3
import httpx

from ms_oauth.callback import wait_for_callback
from ms_oauth.cookies import cookies_from_header, cookies_to_header
from ms_oauth.oauth import parse_oauth_url

LIVE_DOMAINS = (
    "login.live.com",
    "live.com",
    "login.microsoftonline.com",
    "microsoftonline.com",
    "account.live.com",
)


def load_chrome_cookies() -> httpx.Cookies:
    cookies = httpx.Cookies()
    seen: set[tuple[str, str]] = set()
    for domain in LIVE_DOMAINS:
        try:
            jar = browser_cookie3.chrome(domain_name=domain)
        except browser_cookie3.BrowserCookieError:
            continue
        for cookie in jar:
            key = (cookie.name, cookie.domain or domain)
            if key in seen:
                continue
            seen.add(key)
            cookies.set(cookie.name, cookie.value, domain=cookie.domain or domain)
    if not seen:
        raise RuntimeError(
            "Microsoft cookies not found in Chrome. Log in at login.live.com or pass --cookies."
        )
    return cookies


def extract_code_from_location(location: str, redirect_uri: str) -> str | None:
    base = redirect_uri.split("?")[0].rstrip("/")
    if not location.startswith(base):
        return None
    return httpx.URL(location).params.get("code")


def extract_code_from_html(body: str, redirect_uri: str) -> str | None:
    patterns = (
        rf'location\.replace\(["\']({re.escape(redirect_uri)}[^"\']*)["\']',
        rf'window\.location\s*=\s*["\']({re.escape(redirect_uri)}[^"\']*)["\']',
        rf'href=["\']({re.escape(redirect_uri)}[^"\']*)["\']',
    )
    for pattern in patterns:
        match = re.search(pattern, body, re.IGNORECASE)
        if match:
            return extract_code_from_location(match.group(1), redirect_uri)
    return None


def authorize_with_cookies(
    authorize_url: str,
    redirect_uri: str,
    cookies: httpx.Cookies,
    timeout: float = 30.0,
) -> dict[str, str | None]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    with httpx.Client(cookies=cookies, headers=headers, follow_redirects=False, timeout=timeout) as client:
        url = authorize_url
        for _ in range(25):
            response = client.get(url)
            location = response.headers.get("location")
            if location:
                code = extract_code_from_location(location, redirect_uri)
                if code:
                    return {
                        "code": code,
                        "callback_url": location,
                        "state": httpx.URL(location).params.get("state"),
                    }
                url = httpx.URL(location)
                continue

            content_type = response.headers.get("content-type", "")
            if response.status_code == 200 and "text/html" in content_type:
                code = extract_code_from_html(response.text, redirect_uri)
                if code:
                    callback = f"{redirect_uri.split('?')[0]}?code={code}"
                    return {"code": code, "callback_url": callback, "state": None}

            if response.status_code in (401, 403):
                raise RuntimeError("Microsoft rejected cookies (login required)")

            raise RuntimeError(
                f"Unexpected OAuth response: HTTP {response.status_code} without redirect to {redirect_uri}"
            )

    raise RuntimeError("Too many redirects during OAuth authorize")


def exchange_code_for_token(
    client_id: str,
    redirect_uri: str,
    code: str,
    code_verifier: str | None = None,
) -> dict:
    token_urls = (
        "https://login.live.com/oauth20_token.srf",
        "https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
    )
    data = {
        "client_id": client_id,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }
    if code_verifier:
        data["code_verifier"] = code_verifier

    last_error = None
    for token_url in token_urls:
        response = httpx.post(
            token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30.0,
        )
        if response.status_code == 200:
            return response.json()
        last_error = response.text

    raise RuntimeError(f"Token exchange failed: {last_error}")


def load_cookies_file(path: str) -> httpx.Cookies:
    payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    header = payload.get("cookie_header") or cookies_to_header(payload.get("cookies", []))
    if not header:
        raise RuntimeError(f"No cookies found in {path}")
    return cookies_from_header(header)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Complete Microsoft OAuth authorize using browser cookies."
    )
    parser.add_argument("url", help="Full OAuth authorize URL")
    parser.add_argument("--cookies", help='Cookie header, e.g. "MSPAuth=...; MSPProf=..."')
    parser.add_argument("--cookies-file", help="JSON file saved by browser_login.py")
    parser.add_argument("--listen", action="store_true", help="Wait for browser redirect on localhost")
    parser.add_argument("--exchange", action="store_true", help="Exchange authorization code for MSA tokens")
    parser.add_argument("--code-verifier", help="PKCE code_verifier")
    parser.add_argument("--json", action="store_true", help="Print result as JSON")
    args = parser.parse_args()

    oauth = parse_oauth_url(args.url)

    if args.cookies_file:
        cookies = load_cookies_file(args.cookies_file)
    elif args.cookies:
        cookies = cookies_from_header(args.cookies)
    else:
        cookies = load_chrome_cookies()

    try:
        result = authorize_with_cookies(oauth["authorize_url"], oauth["redirect_uri"], cookies)
    except RuntimeError as exc:
        if not args.listen:
            print(f"Cookie authorize failed: {exc}", file=sys.stderr)
            print("Tip: pass --listen to wait for browser redirect on localhost.", file=sys.stderr)
            return 1
        print(f"Cookie authorize failed, waiting on {oauth['redirect_uri']} ...", file=sys.stderr)
        result = wait_for_callback(oauth["redirect_uri"])

    output: dict[str, object] = {
        "callback_url": result["callback_url"],
        "code": result["code"],
        "state": result["state"],
        "redirect_uri": oauth["redirect_uri"],
        "client_id": oauth["client_id"],
    }

    if args.exchange:
        if not result["code"]:
            print("No authorization code captured", file=sys.stderr)
            return 1
        if oauth["code_challenge"] and not args.code_verifier:
            print("Authorize URL uses PKCE; pass --code-verifier", file=sys.stderr)
            return 1
        output["tokens"] = exchange_code_for_token(
            oauth["client_id"],
            oauth["redirect_uri"],
            result["code"],
            args.code_verifier,
        )

    if args.json:
        print(json.dumps(output, indent=2))
    else:
        print(output["callback_url"])
        if args.exchange and "tokens" in output:
            print(json.dumps(output["tokens"], indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
