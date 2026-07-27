from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Lock, Thread
from typing import Callable
from urllib.parse import parse_qs, urlparse

_active_callback_server: ThreadingHTTPServer | None = None
_server_lock = Lock()
_slot_lock = Lock()
_slot: dict[str, object] = {
    "done": Event(),
    "result": {"code": None, "state": None, "callback_url": None},
    "redirect_uri": "",
    "path": "/",
    "on_hit": None,
}


def build_callback_url(redirect_uri: str, query: str) -> str:
    base = redirect_uri.split("?")[0]
    if not query:
        return base
    return f"{base}?{query.lstrip('?')}"


def _callback_handler_factory() -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            with _slot_lock:
                redirect_uri = str(_slot["redirect_uri"])
                path = str(_slot["path"])
                result = _slot["result"]
                done = _slot["done"]
                on_hit = _slot["on_hit"]

            if not redirect_uri:
                self.send_response(404)
                self.end_headers()
                return

            req_path = urlparse(self.path).path
            if not (req_path == path or req_path.startswith(path.rstrip("/"))):
                self.send_response(404)
                self.end_headers()
                return

            query = parse_qs(urlparse(self.path).query)
            result["code"] = query.get("code", [None])[0]
            result["state"] = query.get("state", [None])[0]
            result["callback_url"] = build_callback_url(redirect_uri, urlparse(self.path).query)

            if on_hit:
                payload = on_hit(result)
                if payload is not None:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    done.set()
                    return

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><body><h2>Login OK</h2></body></html>")
            done.set()

        def log_message(self, format: str, *args) -> None:
            return

    return Handler


def _ensure_callback_server(host: str, port: int) -> bool:
    global _active_callback_server
    with _server_lock:
        if _active_callback_server is not None:
            return True
        try:
            server = ThreadingHTTPServer((host, port), _callback_handler_factory())
            server.daemon_threads = True
        except OSError:
            return False
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        _active_callback_server = server
        return True


def reset_callback_slot() -> None:
    with _slot_lock:
        done = _slot["done"]
        if isinstance(done, Event):
            done.clear()
        _slot["result"] = {"code": None, "state": None, "callback_url": None}
        _slot["redirect_uri"] = ""
        _slot["path"] = "/"
        _slot["on_hit"] = None


def stop_callback_server() -> None:
    reset_callback_slot()


def start_callback_server(
    redirect_uri: str,
    *,
    threading: bool = False,
    on_hit: Callable[[dict[str, str | None]], bytes | None] | None = None,
) -> tuple[Event, dict[str, str | None], ThreadingHTTPServer | None]:
    parsed = urlparse(redirect_uri)
    host = parsed.hostname or "127.0.0.1"
    if host in ("localhost", "127.0.0.1"):
        host = "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"

    if not _ensure_callback_server(host, port):
        done = Event()
        return done, {"code": None, "state": None, "callback_url": None}, None

    done = Event()
    result: dict[str, str | None] = {
        "code": None,
        "state": None,
        "callback_url": None,
    }
    with _slot_lock:
        _slot["done"] = done
        _slot["result"] = result
        _slot["redirect_uri"] = redirect_uri
        _slot["path"] = path
        _slot["on_hit"] = on_hit

    return done, result, _active_callback_server


def wait_for_callback(
    redirect_uri: str,
    timeout: float = 120.0,
    *,
    on_hit: Callable[[dict[str, str | None]], bytes | None] | None = None,
) -> dict[str, str | None]:
    done, result, server = start_callback_server(redirect_uri, threading=False, on_hit=on_hit)
    if server is None:
        raise RuntimeError(f"Не удалось занять порт из redirect_uri: {redirect_uri}")

    try:
        if not done.wait(timeout):
            raise TimeoutError(f"Callback не получен на {redirect_uri} за {timeout}s")
        return result
    finally:
        reset_callback_slot()
