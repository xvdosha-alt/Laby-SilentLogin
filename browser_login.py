#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from urllib.parse import parse_qs, urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from ms_oauth.callback import start_callback_server
from ms_oauth.cookies import cookies_to_header, filter_microsoft_cookies
from ms_oauth.oauth import parse_oauth_url
from ms_oauth.paths import CHROMIUM_PROFILE, COOKIES_FILE

DEFAULT_OAUTH_URL = (
    "https://login.live.com/oauth20_authorize.srf"
    "?client_id=27843883-6e3b-42cb-9e51-4f55a700601e"
    "&response_type=code"
    "&cobrandid=8058f65d-ce06-4c30-9559-473c9275a65d"
    "&redirect_uri=http://localhost:8086"
    "&scope=XboxLive.signin%20offline_access"
    "&prompt=select_account"
    "&response_mode=query"
)


def wait_for_login(oauth_url: str, profile_dir: Path, timeout_sec: float) -> dict[str, object]:
    oauth = parse_oauth_url(oauth_url)
    redirect_uri = oauth["redirect_uri"]
    redirect = urlparse(redirect_uri)
    localhost_pattern = f"{redirect.scheme}://{redirect.netloc}/**"

    done, callback, server = start_callback_server(redirect_uri)

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1100, "height": 820},
            locale="en-US",
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(oauth_url, wait_until="domcontentloaded")

        print("Chromium opened. Sign in to your Microsoft / Minecraft account.", file=sys.stderr)
        print(f"Waiting for redirect to {redirect_uri} ...", file=sys.stderr)

        try:
            page.wait_for_url(localhost_pattern, timeout=int(timeout_sec * 1000))
            current = page.url
            if not callback["code"]:
                query = parse_qs(urlparse(current).query)
                callback["code"] = query.get("code", [None])[0]
                callback["state"] = query.get("state", [None])[0]
                callback["callback_url"] = current
        except PlaywrightTimeoutError:
            if server is not None and done.wait(timeout=1):
                pass
            else:
                context.close()
                if server is not None:
                    server.shutdown()
                raise TimeoutError(
                    f"Login timed out after {timeout_sec}s. Finish sign-in in the Chromium window."
                )

        cookies = filter_microsoft_cookies(context.cookies())
        context.close()

    if server is not None:
        server.shutdown()

    if not callback["callback_url"] and callback["code"]:
        query = f"code={callback['code']}"
        if callback["state"]:
            query += f"&state={callback['state']}"
        callback["callback_url"] = f"{redirect_uri.split('?')[0]}?{query}"

    return {
        "callback_url": callback["callback_url"],
        "code": callback["code"],
        "state": callback["state"],
        "cookies": cookies,
        "cookie_header": cookies_to_header(cookies),
        "redirect_uri": redirect_uri,
    }


def save_session(output: Path, payload: dict[str, object]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.chmod(output, 0o600)


def main() -> int:
    parser = argparse.ArgumentParser(description="Open Chromium for Microsoft login and save cookies.")
    parser.add_argument("url", nargs="?", default=DEFAULT_OAUTH_URL, help="OAuth authorize URL")
    parser.add_argument("--profile-dir", default=str(CHROMIUM_PROFILE))
    parser.add_argument("--save", default=str(COOKIES_FILE))
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    profile_dir = Path(args.profile_dir).expanduser()
    profile_dir.mkdir(parents=True, exist_ok=True)
    save_path = Path(args.save).expanduser()

    try:
        result = wait_for_login(args.url, profile_dir, args.timeout)
    except TimeoutError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Login failed: {exc}", file=sys.stderr)
        return 1

    payload = {
        "oauth_url": args.url,
        "callback_url": result["callback_url"],
        "code": result["code"],
        "state": result["state"],
        "redirect_uri": result["redirect_uri"],
        "cookie_header": result["cookie_header"],
        "cookies": result["cookies"],
    }
    save_session(save_path, payload)

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(result["callback_url"])
        print(f"Saved cookies: {save_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
