# Silent OAuth Login

Тихая Microsoft OAuth-авторизация для Minecraft-лаунчеров: вставляешь authorize URL — получаешь localhost callback с `code`, без ручного входа на login.live.com.

## Быстрый старт

```bash
cd ms-oauth-login
./scripts/run_login.sh
./scripts/run_web.sh
```

Открой http://127.0.0.1:8799/

1. Один раз запусти `run_login.sh` — войди в Microsoft, cookies сохранятся.
2. Вставь authorize URL из лаунчера в веб-интерфейс.
3. После авторизации браузер перейдёт на `http://localhost:8086/?code=...`.

## Скрипты

| Скрипт | Описание |
|--------|----------|
| `./scripts/run_web.sh` | Веб-интерфейс на порту 8799 |
| `./scripts/run_login.sh` | Вход через Chromium для обновления cookies |
| `./scripts/run_cookie.sh` | CLI-авторизация по cookies |

## Переменные окружения

| Переменная | По умолчанию | Описание |
|------------|--------------|----------|
| `UI_HOST` | `127.0.0.1` | Адрес привязки веб-сервера |
| `UI_PORT` | `8799` | Порт веб-сервера |
| `MS_OAUTH_NO_BROWSER` | — | `1` — не открывать браузер при старте |

## Данные

Хранятся в `~/.free_labymod/ms-oauth-login/`:

- `ms_cookies.json` — cookies сессии Microsoft
- `chromium-profile/` — профиль Playwright для fallback-авторизации

## Деплой на сервер

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/playwright install chromium
.venv/bin/playwright install-deps chromium
```

Шаблоны: `deploy/ms-oauth-login.service` и `deploy/nginx.example.conf`.

```bash
export UI_HOST=127.0.0.1
export UI_PORT=8792
export MS_OAUTH_NO_BROWSER=1
export PYTHONPATH=/opt/ms-oauth-login
.venv/bin/python web_login.py
```

## Требования

- Python 3.10+
- Playwright Chromium (fallback для страницы согласия Microsoft)
