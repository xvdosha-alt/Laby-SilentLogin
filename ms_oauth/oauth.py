from urllib.parse import parse_qs, quote, urlencode, urlparse, urlunparse


def parse_oauth_url(url: str, *, require_localhost: bool = False) -> dict[str, str]:
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Ссылка должна начинаться с http:// или https://")
    params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    redirect_uri = params.get("redirect_uri")
    if not redirect_uri:
        raise ValueError("В ссылке нет redirect_uri")

    redirect = urlparse(redirect_uri)
    if require_localhost and redirect.hostname not in ("localhost", "127.0.0.1"):
        raise ValueError("redirect_uri должен быть localhost")

    if redirect.port is not None:
        redirect_port = redirect.port
    elif redirect.scheme == "https":
        redirect_port = 443
    else:
        redirect_port = 80

    bind_host = "127.0.0.1"
    if redirect.hostname and redirect.hostname not in ("localhost", "127.0.0.1"):
        bind_host = redirect.hostname

    return {
        "authorize_url": url.strip(),
        "redirect_uri": redirect_uri,
        "redirect_host": bind_host,
        "redirect_port": redirect_port,
        "redirect_path": redirect.path or "/",
        "client_id": params.get("client_id", ""),
        "scope": params.get("scope", ""),
        "response_type": params.get("response_type", "code"),
        "response_mode": params.get("response_mode", ""),
        "prompt": params.get("prompt", ""),
        "state": params.get("state", ""),
        "code_challenge": params.get("code_challenge", ""),
        "code_challenge_method": params.get("code_challenge_method", ""),
    }


def silent_authorize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    params.pop("prompt", None)
    query = urlencode(params, quote_via=quote)
    return urlunparse(parsed._replace(query=query))
