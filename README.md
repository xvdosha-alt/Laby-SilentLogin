EN | [RU](docs/README_RU.md)

# Silent OAuth Login

![Python](https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white)


Silent Microsoft OAuth auth for Minecraft launchers: paste an authorize URL and get a localhost callback with `code`, without manual login on login.live.com.

## Quick start

```bash
cd ms-oauth-login
./scripts/run_login.sh
./scripts/run_web.sh
```

Open http://127.0.0.1:8799/

1. Run `run_login.sh` once - sign in to Microsoft, cookies will be saved.
2. Paste the authorize URL from the launcher into the web UI.
3. After auth, the browser redirects to `http://localhost:8086/?code=...`.

## Scripts

| Script | Description |
|--------|----------|
| `./scripts/run_web.sh` | Web UI on port 8799 |
| `./scripts/run_login.sh` | Sign in via Chromium to refresh cookies |
| `./scripts/run_cookie.sh` | CLI auth via cookies |

## Environment variables

| Variable | Default | Description |
|------------|--------------|----------|
| `UI_HOST` | `127.0.0.1` | Web server bind address |
| `UI_PORT` | `8799` | Web server port |
| `MS_OAUTH_NO_BROWSER` | - | `1` - do not open browser on start |

## Data

Stored in `~/.free_labymod/ms-oauth-login/`:

- `ms_cookies.json` - Microsoft session cookies
- `chromium-profile/` - Playwright profile for fallback auth

## Server deploy

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
.venv/bin/playwright install-deps chromium
```

Templates: `deploy/ms-oauth-login.service` and `deploy/nginx.example.conf`.

```bash
export UI_HOST=127.0.0.1
export UI_PORT=8792
export MS_OAUTH_NO_BROWSER=1
export PYTHONPATH=/opt/ms-oauth-login
.venv/bin/python web_login.py
```

## Requirements

- Python 3.10+
- Playwright Chromium (fallback for Microsoft consent page)
