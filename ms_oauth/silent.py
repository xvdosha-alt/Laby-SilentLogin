from __future__ import annotations

import html as html_lib
import json
import re
import threading
from pathlib import Path

import browser_cookie3
import httpx
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from ms_oauth.callback import reset_callback_slot, start_callback_server
from ms_oauth.cookies import cookies_from_header, cookies_to_header
from ms_oauth.oauth import silent_authorize_url
from ms_oauth.paths import CHROMIUM_PROFILE, COOKIES_FILE

LEGACY_COOKIES_FILE = Path.home() / ".free_labymod" / "ms_cookies.json"
_auth_lock = threading.Lock()

LIVE_DOMAINS = (
    "login.live.com",
    "live.com",
    "login.microsoftonline.com",
    "microsoftonline.com",
    "account.live.com",
)


class SilentAuthError(RuntimeError):
    pass


def _cookie_paths() -> list[Path]:
    paths = [p for p in (COOKIES_FILE, LEGACY_COOKIES_FILE) if p.exists()]
    return sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)


def load_session_cookies() -> httpx.Cookies:
    for path in _cookie_paths():
        payload = json.loads(path.read_text(encoding="utf-8"))
        header = payload.get("cookie_header") or cookies_to_header(payload.get("cookies", []))
        if header:
            return cookies_from_header(header)

    cookies = httpx.Cookies()
    seen: set[tuple[str, str]] = set()
    loaders = (
        getattr(browser_cookie3, "firefox", None),
        browser_cookie3.chrome,
    )
    for loader in loaders:
        if loader is None:
            continue
        for domain in LIVE_DOMAINS:
            try:
                jar = loader(domain_name=domain)
            except browser_cookie3.BrowserCookieError:
                continue
            for cookie in jar:
                key = (cookie.name, cookie.domain or domain)
                if key in seen:
                    continue
                seen.add(key)
                cookies.set(cookie.name, cookie.value, domain=cookie.domain or domain)

    if not seen:
        raise SilentAuthError(
            "Нет сохранённых Microsoft cookies. Сначала выполни: ./scripts/run_login.sh"
        )
    return cookies


def _extract_code_from_location(location: str, redirect_uri: str) -> str | None:
    base = redirect_uri.split("?")[0].rstrip("/")
    if not location.startswith(base):
        return None
    return httpx.URL(location).params.get("code")


def _extract_code_from_body(body: str, redirect_uri: str) -> str | None:
    base = re.escape(redirect_uri.split("?")[0])
    patterns = (
        rf"location\.replace\(['\"]({base}[^'\"]*)['\"]",
        rf"window\.location\s*=\s*['\"]({base}[^'\"]*)['\"]",
        rf"href=['\"]({base}[^'\"]*)['\"]",
        r"http://localhost:\d+\?code=([^&\"'\s]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, body, re.IGNORECASE)
        if not match:
            continue
        value = match.group(1)
        if value.startswith("http"):
            return _extract_code_from_location(value, redirect_uri)
        return value
    return None


def _build_callback(redirect_uri: str, code: str, state: str | None = None) -> str:
    base = redirect_uri.split("?")[0]
    query = f"code={code}"
    if state:
        query += f"&state={state}"
    return f"{base}?{query}"


def _parse_html_form(body: str) -> tuple[str, str, dict[str, str]] | None:
    match = re.search(
        r'<form[^>]*action="([^"]+)"[^>]*method="([^"]+)"',
        body,
        re.IGNORECASE,
    )
    if not match:
        return None

    action = html_lib.unescape(match.group(1))
    method = match.group(2).lower()
    fields: dict[str, str] = {}
    for tag in re.findall(r"<input[^>]+>", body, re.IGNORECASE):
        name_match = re.search(r'name="([^"]+)"', tag, re.IGNORECASE)
        if not name_match:
            continue
        value_match = re.search(r'value="([^"]*)"', tag, re.IGNORECASE)
        fields[name_match.group(1)] = html_lib.unescape(value_match.group(1) if value_match else "")
    if not fields:
        return None
    return action, method, fields


def _load_playwright_cookies() -> list[dict[str, object]]:
    for path in _cookie_paths():
        payload = json.loads(path.read_text(encoding="utf-8"))
        cookies = payload.get("cookies", [])
        if not cookies:
            continue
        result: list[dict[str, object]] = []
        for cookie in cookies:
            item: dict[str, object] = {
                "name": cookie["name"],
                "value": cookie["value"],
                "domain": cookie.get("domain") or ".live.com",
                "path": cookie.get("path") or "/",
            }
            expires = cookie.get("expires")
            if expires:
                item["expires"] = int(expires)
            if cookie.get("httpOnly"):
                item["httpOnly"] = True
            if cookie.get("secure"):
                item["secure"] = True
            same_site = cookie.get("sameSite")
            if same_site in ("Strict", "Lax", "None"):
                item["sameSite"] = same_site
            result.append(item)
        return result
    return []


def _resolve_location(response: httpx.Response, location: str) -> str:
    if location.startswith("/"):
        return str(httpx.URL(str(response.url)).join(location))
    return location


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
        response = client.get(authorize_url)
        for _ in range(30):
            location = response.headers.get("location")
            if location:
                location = _resolve_location(response, location)
                code = _extract_code_from_location(location, redirect_uri)
                if code:
                    return {
                        "code": code,
                        "callback_url": location,
                        "state": httpx.URL(location).params.get("state"),
                    }
                response = client.get(location)
                continue

            if response.status_code == 200 and "text/html" in response.headers.get("content-type", ""):
                body = response.text
                if 'id="i0116"' in body or "Sign in to Minecraft" in body:
                    raise SilentAuthError(
                        "Сессия Microsoft истекла. Обнови cookies: ./scripts/run_login.sh"
                    )
                code = _extract_code_from_body(body, redirect_uri)
                if code:
                    callback = _build_callback(redirect_uri, code)
                    return {"code": code, "callback_url": callback, "state": None}

                form = _parse_html_form(body)
                if form and (
                    'id="fmHF"' in body
                    or "account.live.com/App/Confirm" in form[0]
                    or "DoSubmit()" in body
                ):
                    action, method, fields = form
                    if method == "post":
                        response = client.post(action, data=fields)
                    else:
                        response = client.get(action, params=fields)
                    continue

                if "account.live.com/App/Confirm" in str(response.url):
                    raise SilentAuthError(
                        "Нужно подтверждение доступа Microsoft. Повтори запрос."
                    )

            if response.status_code in (401, 403):
                raise SilentAuthError("Microsoft отклонил cookies")

            raise SilentAuthError(
                f"Неожиданный ответ OAuth: HTTP {response.status_code}"
            )

    raise SilentAuthError("Слишком много редиректов OAuth")


def authorize_with_playwright(
    authorize_url: str,
    redirect_uri: str,
    profile_dir: Path,
    timeout_sec: float = 90.0,
) -> dict[str, str | None]:
    redirect = httpx.URL(redirect_uri)
    pattern = f"{redirect.scheme}://{redirect.host}:{redirect.port}/**"
    silent_url = silent_authorize_url(authorize_url)
    redirect_base = redirect_uri.split("?")[0]

    done, callback, server = start_callback_server(redirect_uri, threading=True)

    profile_dir.mkdir(parents=True, exist_ok=True)
    playwright_cookies = _load_playwright_cookies()
    context = None

    try:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            if playwright_cookies:
                context.add_cookies(playwright_cookies)
            page = context.new_page()
            page.goto(silent_url, wait_until="domcontentloaded", timeout=int(timeout_sec * 1000))

            deadline = timeout_sec
            while deadline > 0:
                if callback["code"]:
                    return {
                        "code": callback["code"],
                        "callback_url": callback["callback_url"],
                        "state": callback["state"],
                    }

                current = page.url
                if current.startswith(redirect_base):
                    code = httpx.URL(current).params.get("code")
                    if code:
                        return {
                            "code": code,
                            "callback_url": current,
                            "state": httpx.URL(current).params.get("state"),
                        }

                if "account.live.com/App/Confirm" in current:
                    for selector in ("input[name='appConfirmContinue']", "#appConfirmContinue"):
                        try:
                            page.locator(selector).first.click(force=True, timeout=3000)
                            break
                        except Exception:
                            continue
                    page.wait_for_load_state("domcontentloaded")
                    deadline -= 3
                    continue

                if "login.live.com" in current and page.locator("#i0116").count():
                    raise SilentAuthError(
                        "Сессия Microsoft истекла. Обнови cookies: ./scripts/run_login.sh"
                    )

                try:
                    page.wait_for_url(pattern, timeout=3000)
                    current = page.url
                    code = httpx.URL(current).params.get("code")
                    if not code:
                        raise SilentAuthError("Redirect на localhost без code")
                    return {
                        "code": code,
                        "callback_url": current,
                        "state": httpx.URL(current).params.get("state"),
                    }
                except PlaywrightTimeoutError:
                    deadline -= 3

            raise SilentAuthError(f"Не дождались redirect на {redirect_uri}")
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
        if server is not None:
            reset_callback_slot()


def authorize_silent(
    authorize_url: str,
    redirect_uri: str,
    *,
    profile_dir: Path = CHROMIUM_PROFILE,
) -> dict[str, str | None]:
    with _auth_lock:
        silent_url = silent_authorize_url(authorize_url)
        cookies = load_session_cookies()
        cookie_error: SilentAuthError | None = None
        try:
            return authorize_with_cookies(silent_url, redirect_uri, cookies)
        except SilentAuthError as exc:
            cookie_error = exc

        try:
            return authorize_with_playwright(authorize_url, redirect_uri, profile_dir)
        except SilentAuthError as exc:
            cookie_error = exc

        raise cookie_error or SilentAuthError("Не удалось получить code")
