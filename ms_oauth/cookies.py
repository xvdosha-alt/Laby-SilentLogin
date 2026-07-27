import httpx

MICROSOFT_COOKIE_DOMAINS = (
    "login.live.com",
    "live.com",
    "login.microsoftonline.com",
    "microsoftonline.com",
    "account.live.com",
    "microsoft.com",
)


def cookies_to_header(cookies: list[dict]) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for cookie in cookies:
        name = cookie.get("name")
        value = cookie.get("value")
        if not name or value is None or name in seen:
            continue
        seen.add(name)
        parts.append(f"{name}={value}")
    return "; ".join(parts)


def cookies_from_header(header: str) -> httpx.Cookies:
    cookies = httpx.Cookies()
    for part in header.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        cookies.set(name.strip(), value.strip())
    return cookies


def filter_microsoft_cookies(cookies: list[dict]) -> list[dict]:
    result: list[dict] = []
    for cookie in cookies:
        domain = (cookie.get("domain") or "").lstrip(".")
        if any(domain == allowed or domain.endswith("." + allowed) for allowed in MICROSOFT_COOKIE_DOMAINS):
            result.append(cookie)
    return result
