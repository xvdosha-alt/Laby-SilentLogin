#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import mimetypes
import os
import socket
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ms_oauth.oauth import parse_oauth_url
from ms_oauth.silent import SilentAuthError, authorize_silent

UI_PORT = int(os.environ.get("UI_PORT", "8799"))
UI_HOST = os.environ.get("UI_HOST", "127.0.0.1")
STATIC_DIR = Path(__file__).resolve().parent / "static"


def port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return True
        except OSError:
            return False


def dirt_background_html() -> str:
    layers: dict[str, list[tuple[float, float, int, float]]] = {
        "back": [
            (4, 6, 88, 0.16),
            (72, 8, 104, 0.14),
            (38, 72, 96, 0.13),
            (84, 58, 80, 0.12),
            (12, 48, 72, 0.11),
        ],
        "mid": [
            (18, 18, 64, 0.24),
            (58, 28, 72, 0.22),
            (8, 62, 56, 0.2),
            (76, 38, 68, 0.21),
            (44, 82, 60, 0.19),
            (90, 78, 52, 0.18),
        ],
        "front": [
            (28, 10, 48, 0.32),
            (62, 52, 44, 0.3),
            (6, 34, 40, 0.28),
            (82, 22, 52, 0.31),
            (48, 44, 36, 0.27),
            (22, 78, 42, 0.26),
            (94, 44, 38, 0.25),
        ],
    }
    depths = {"back": "0.028", "mid": "0.055", "front": "0.09"}
    parts: list[str] = ['<div class="dirt-bg" id="dirt-bg" aria-hidden="true">']
    for name, blocks in layers.items():
        parts.append(f'<div class="dirt-layer dirt-layer--{name}" data-depth="{depths[name]}">')
        for left, top, size, opacity in blocks:
            parts.append(
                f'<div class="dirt-block" style="left:{left}%;top:{top}%;width:{size}px;height:{size}px;opacity:{opacity}"></div>'
            )
        parts.append("</div>")
    parts.append('<div class="dirt-overlay"></div></div>')
    return "".join(parts)


def page_shell(title: str, body: str) -> bytes:
    doc = f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --bg: #1a1f16;
      --card: #242b20;
      --card2: #2d3628;
      --text: #f5f7f2;
      --muted: #a8b5a0;
      --accent: #5cdb5c;
      --accent-hover: #4bc94b;
      --danger: #ff8a8a;
      --line: rgba(255,255,255,.08);
      --shadow: 0 20px 50px rgba(0,0,0,.35);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      color: var(--text);
      background: #141810;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 20px;
      position: relative;
      overflow-x: hidden;
    }}
    .dirt-bg {{
      position: fixed;
      inset: 0;
      z-index: 0;
      pointer-events: none;
      overflow: hidden;
    }}
    .dirt-layer {{
      position: absolute;
      inset: -10%;
      will-change: transform;
    }}
    .dirt-block {{
      position: absolute;
      background: url("/static/dirt.png") center / cover no-repeat;
      image-rendering: pixelated;
      image-rendering: crisp-edges;
      border-radius: 4px;
      box-shadow:
        0 10px 24px rgba(0,0,0,.35),
        inset 0 0 0 2px rgba(255,255,255,.04);
    }}
    .dirt-overlay {{
      position: absolute;
      inset: 0;
      background:
        radial-gradient(circle at 50% 20%, rgba(92,219,92,.08), transparent 42%),
        linear-gradient(180deg, rgba(20,24,16,.72), rgba(20,24,16,.88));
    }}
    .page-content {{
      position: relative;
      z-index: 1;
      width: min(560px, 100%);
    }}
    .header {{
      margin-bottom: 18px;
    }}
    .header-title {{
      font-size: 20px;
      font-weight: 700;
      letter-spacing: -.02em;
    }}
    .card {{
      background: rgba(36, 43, 32, 0.92);
      backdrop-filter: blur(8px);
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 24px;
      box-shadow: var(--shadow);
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 24px;
      font-weight: 700;
    }}
    .lead {{
      color: var(--muted);
      line-height: 1.5;
      margin: 0 0 20px;
      font-size: 15px;
    }}
    label {{
      display: block;
      font-size: 14px;
      font-weight: 600;
      margin-bottom: 8px;
    }}
    textarea {{
      width: 100%;
      min-height: 96px;
      resize: vertical;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: var(--card2);
      color: var(--text);
      padding: 14px 16px;
      font-family: inherit;
      font-size: 14px;
      line-height: 1.45;
      outline: none;
    }}
    textarea:focus {{
      border-color: rgba(92,219,92,.5);
      box-shadow: 0 0 0 3px rgba(92,219,92,.12);
    }}
    textarea::placeholder {{ color: #7d8878; }}
    .btn {{
      width: 100%;
      margin-top: 16px;
      border: none;
      border-radius: 14px;
      padding: 15px 18px;
      font-family: inherit;
      font-size: 16px;
      font-weight: 600;
      cursor: pointer;
      transition: transform .15s, background .15s, opacity .15s;
    }}
    .btn:disabled {{ opacity: .65; cursor: wait; }}
    .btn-primary {{
      background: var(--accent);
      color: #163416;
    }}
    .btn-primary:hover:not(:disabled) {{ background: var(--accent-hover); transform: translateY(-1px); }}
    .btn-row {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-top: 12px;
    }}
    .btn-secondary {{
      background: var(--card2);
      color: var(--text);
      border: 1px solid var(--line);
      margin-top: 0;
    }}
    .alert {{
      margin-top: 16px;
      padding: 14px 16px;
      border-radius: 14px;
      font-size: 14px;
      line-height: 1.5;
    }}
    .alert-error {{
      background: rgba(255,100,100,.1);
      border: 1px solid rgba(255,100,100,.2);
      color: #ffd0d0;
    }}
    .result-panel {{
      margin-top: 18px;
      padding: 16px;
      border-radius: 14px;
      background: rgba(92,219,92,.06);
      border: 1px solid rgba(92,219,92,.18);
    }}
    .result-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 14px;
    }}
    .result-title {{
      font-size: 14px;
      font-weight: 600;
    }}
    .badge {{
      font-size: 11px;
      font-weight: 600;
      letter-spacing: .04em;
      text-transform: uppercase;
      color: var(--accent);
      background: rgba(92,219,92,.12);
      padding: 4px 8px;
      border-radius: 999px;
    }}
    .field {{
      margin-bottom: 12px;
    }}
    .field:last-child {{ margin-bottom: 0; }}
    .field-label {{
      display: block;
      font-size: 12px;
      font-weight: 600;
      color: var(--muted);
      margin-bottom: 6px;
    }}
    .field-value {{
      padding: 10px 12px;
      border-radius: 10px;
      background: var(--card2);
      border: 1px solid var(--line);
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 12px;
      line-height: 1.45;
      word-break: break-all;
      color: #dbe4d6;
    }}
    .toast {{
      position: fixed;
      bottom: 24px;
      left: 50%;
      transform: translateX(-50%) translateY(20px);
      opacity: 0;
      background: #2f382b;
      color: var(--text);
      padding: 12px 18px;
      border-radius: 999px;
      font-size: 14px;
      box-shadow: var(--shadow);
      transition: .25s;
      pointer-events: none;
    }}
    .toast.show {{ opacity: 1; transform: translateX(-50%) translateY(0); }}
    .spinner {{
      display: inline-block;
      width: 16px;
      height: 16px;
      border: 2px solid rgba(22,52,22,.25);
      border-top-color: #163416;
      border-radius: 999px;
      animation: spin .7s linear infinite;
      vertical-align: -3px;
      margin-right: 8px;
    }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
  </style>
</head>
<body>
  {dirt_background_html()}
  <div class="page-content">
  {body}
  </div>
  <div class="toast" id="toast">Скопировано</div>
  <script>
    (function () {{
      const layers = document.querySelectorAll(".dirt-layer");
      let targetX = 0;
      let targetY = 0;
      let currentX = 0;
      let currentY = 0;

      document.addEventListener("mousemove", (event) => {{
        targetX = (event.clientX / window.innerWidth - 0.5) * 2;
        targetY = (event.clientY / window.innerHeight - 0.5) * 2;
      }});

      function tick() {{
        currentX += (targetX - currentX) * 0.07;
        currentY += (targetY - currentY) * 0.07;
        layers.forEach((layer) => {{
          const depth = Number(layer.dataset.depth || 0.05);
          const moveX = currentX * depth * 48;
          const moveY = currentY * depth * 48;
          layer.style.transform = `translate3d(${{moveX}}px, ${{moveY}}px, 0)`;
        }});
        requestAnimationFrame(tick);
      }}

      tick();
    }})();
    function showToast(text) {{
      const t = document.getElementById("toast");
      t.textContent = text;
      t.classList.add("show");
      setTimeout(() => t.classList.remove("show"), 1800);
    }}
    async function copyText(text) {{
      await navigator.clipboard.writeText(text);
      showToast("Скопировано!");
    }}
  </script>
</body>
</html>"""
    return doc.encode("utf-8")


def home_page(error: str = "", oauth_url: str = "") -> bytes:
    error_block = f'<div class="alert alert-error">{html.escape(error)}</div>' if error else ""
    body = f"""
  <div class="wrap">
    <header class="header">
      <div class="header-title">Silent OAuth Login</div>
    </header>
    <main class="card">
      <h1>Authorize URL → callback</h1>
      <p class="lead">Вставь OAuth-ссылку из лаунчера (login.live.com/oauth20_authorize…). На выходе — localhost callback с <code style="font-family:ui-monospace,monospace;font-size:13px;color:#c8d4c3">code</code>.</p>
      <form id="login-form">
        <label for="url">Authorize URL</label>
        <textarea id="url" name="url" placeholder="https://login.live.com/oauth20_authorize.srf?client_id=...&redirect_uri=http://localhost:8086&...">{html.escape(oauth_url)}</textarea>
        <button class="btn btn-primary" type="submit" id="submit-btn">Авторизовать</button>
      </form>
      {error_block}
      <div id="result"></div>
    </main>
  </div>
  <script>
    const form = document.getElementById("login-form");
    const urlField = document.getElementById("url");
    const submitBtn = document.getElementById("submit-btn");
    const defaultLabel = submitBtn.textContent;

    urlField.addEventListener("keydown", (e) => {{
      if (e.key === "Enter") {{
        e.preventDefault();
        form.requestSubmit();
      }}
    }});

    form.addEventListener("submit", async (e) => {{
      e.preventDefault();
      submitBtn.disabled = true;
      submitBtn.innerHTML = '<span class="spinner"></span>Авторизация…';
      document.getElementById("result").innerHTML = "";

      try {{
        const res = await fetch("/", {{
          method: "POST",
          headers: {{ "Content-Type": "application/x-www-form-urlencoded" }},
          body: new URLSearchParams(new FormData(form)),
        }});
        const data = await res.json();

        if (data.callback_url) {{
          document.getElementById("result").innerHTML = '<div class="alert">Переход на callback…</div>';
          window.location.assign(data.callback_url);
          return;
        }}

        if (data.error) {{
          document.getElementById("result").innerHTML = `<div class="alert alert-error">${{data.error}}</div>`;
        }}
      }} catch (_) {{
        document.getElementById("result").innerHTML = '<div class="alert alert-error">Ошибка запроса. Проверь, что сервер запущен.</div>';
      }} finally {{
        submitBtn.disabled = false;
        submitBtn.textContent = defaultLabel;
      }}
    }});
  </script>"""
    return page_shell("Silent OAuth Login", body)


class UIHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, file_path: Path) -> None:
        data = file_path.read_bytes()
        mime, _ = mimetypes.guess_type(str(file_path))
        self.send_response(200)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/favicon.ico":
            icon = b"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><rect width='100' height='100' rx='20' fill='%23242b20'/><text x='50' y='62' font-size='28' font-family='system-ui,sans-serif' font-weight='700' text-anchor='middle' fill='%235cdb5c'>MS</text></svg>"
            self.send_response(200)
            self.send_header("Content-Type", "image/svg+xml")
            self.send_header("Content-Length", str(len(icon)))
            self.end_headers()
            self.wfile.write(icon)
            return
        if path.startswith("/static/"):
            rel = path.removeprefix("/static/").lstrip("/")
            if not rel or ".." in Path(rel).parts:
                self.send_response(404)
                self.end_headers()
                return
            file_path = (STATIC_DIR / rel).resolve()
            if not str(file_path).startswith(str(STATIC_DIR.resolve())) or not file_path.is_file():
                self.send_response(404)
                self.end_headers()
                return
            self._send_file(file_path)
            return
        if path != "/":
            self.send_response(404)
            self.end_headers()
            return
        payload = home_page()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/":
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", "0"))
        if length > 8192:
            self._send_json(413, {"error": "Ссылка слишком длинная"})
            return

        body = self.rfile.read(length).decode("utf-8", errors="replace")
        oauth_url = parse_qs(body).get("url", [""])[0]

        try:
            oauth = parse_oauth_url(oauth_url, require_localhost=True)
            result = authorize_silent(oauth["authorize_url"], oauth["redirect_uri"])
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        except SilentAuthError as exc:
            msg = str(exc)
            if "истекла" in msg or "cookies" in msg:
                msg = "Сессия устарела. Сначала войди в аккаунт через ./scripts/run_login.sh"
            self._send_json(400, {"error": msg})
            return

        self._send_json(
            200,
            {
                "callback_url": result["callback_url"],
                "code": result["code"],
                "state": result["state"],
            },
        )

    def log_message(self, format: str, *args) -> None:
        return


def main() -> int:
    if not port_available(UI_HOST, UI_PORT):
        print(f"Port {UI_PORT} is already in use on {UI_HOST}", file=sys.stderr)
        return 1

    url = f"http://{UI_HOST if UI_HOST != '0.0.0.0' else '127.0.0.1'}:{UI_PORT}/"
    print(url)
    if os.environ.get("MS_OAUTH_NO_BROWSER") != "1":
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    server = ThreadingHTTPServer((UI_HOST, UI_PORT), UIHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
