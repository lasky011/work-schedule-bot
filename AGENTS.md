# AGENTS.md

## Cursor Cloud specific instructions

This repo is **TNG Alice** — a Python 3.12 Telegram bot for restaurant staff work-schedule
management. It has three runnable processes that share one codebase (`services/`,
`repositories/`, config): the main bot (`bot.py`), a FastAPI **Mini App** web/API
(`api/app.py`, served in-process by `bot.py` when `MINIAPP_ENABLED` is set), and a separate
admin bot (`admin_bot.py`). External dependencies for full end-to-end are PostgreSQL
(`DATABASE_URL`), Telegram Bot API (`BOT_TOKEN`), and a Google Sheet (`SHEET_ID`, has a
default). See `app_config.py` for all env vars.

### Environment (already provisioned in the VM snapshot)
- Python deps live in a virtualenv at `.venv` (gitignored). The startup update script keeps it
  in sync with `requirements.txt`. Activate with `source .venv/bin/activate` (or call
  `.venv/bin/python` / `.venv/bin/pip` directly).
- A local **PostgreSQL 16** is installed. It does **not** auto-start — run
  `sudo service postgresql start` at the beginning of a session.
- A dev database + role exist: `postgresql://tng:tng@127.0.0.1:5432/tng_alice`.
- A local `.env` (gitignored) provides dev values, including a **dummy** `BOT_TOKEN`/
  `ADMIN_BOT_TOKEN` and the local `DATABASE_URL`. The dummy tokens are enough for the Mini App
  (Telegram `initData` HMAC auth) and DB work, but you need **real** tokens to actually connect
  to the Telegram Bot API (long-polling in `bot.py`/`admin_bot.py` will fail auth otherwise).

### Lint / test / build
- Lint + tests: `make check` (byte-compiles every module via `py_compile`/`compileall`, then
  runs `smoke_test.py`). This is the only quality gate; there is no ruff/flake8/black config.
- `smoke_test.py` mocks the DB, Telegram, and Google Sheets, so it needs no external services.
- Known gotcha: `smoke_test.py::test_period_coverage_missing` is **time-dependent** — it
  hardcodes July 2026 dates and only passes when "today" falls inside/near that schedule
  period. It fails outside that window (e.g. in August). This is a pre-existing test bug, not an
  environment problem; all other smoke tests pass.
- Build: container only — `docker build -t work-schedule-bot .` (see `Dockerfile`). There is no
  frontend build step; Mini App static assets under `miniapp/static/` are served as-is.

### Running the services (dev)
- DB schema is auto-created on startup by `init_db()` in `bot.py`; the `supabase/migrations/*.sql`
  files are idempotent and overlap with `init_db()`. To (re)create the schema without launching
  the bot: `.venv/bin/python -c "from bot import init_db; init_db()"`.
- Full product (needs a real `BOT_TOKEN`): `MINIAPP_ENABLED=1 python3 bot.py`. This runs the bot
  long-poller plus, in-process, the Mini App HTTP server on `MINIAPP_PORT` (default `8080`,
  health at `GET /api/health`).
- **Run only the Mini App locally without a Telegram token** (useful for testing the web UI/API):
  the FastAPI app is created by `api.app.create_app()`, but it must be launched *after* importing
  `bot` so the departments manager is configured (this happens at `bot` import time, not in
  `create_app()`). One-liner:
  `.venv/bin/python -c "import bot, uvicorn; from api.app import create_app; uvicorn.run(create_app(), host='0.0.0.0', port=8080)"`.
  Launching `uvicorn api.app:create_app --factory` directly will start, but departments will be
  empty (`/api/health` reports `departments: false`) and profile registration will reject names.
- Admin bot (needs real `ADMIN_BOT_TOKEN` + `ADMIN_IDS`): `python3 admin_bot.py`.

### Testing the Mini App end-to-end
The Mini App authenticates via Telegram WebApp `initData` (HMAC-SHA256 over the query string
keyed by `BOT_TOKEN`; see `api/auth.py`). To exercise the API/UI locally, sign `initData` with
the same `BOT_TOKEN` from `.env` and send it as the `X-Telegram-Init-Data` header (see the
`build_signed_init_data` helper in `smoke_test.py`). For the browser UI, load
`http://127.0.0.1:8080/#tgWebAppData=<url-encoded initData>&tgWebAppVersion=7.10&tgWebAppPlatform=web`;
Telegram's `telegram-web-app.js` (loaded from telegram.org, needs internet) populates
`Telegram.WebApp.initData` from that hash. `auth_date` in the signed data must be recent
(within 24h). Note: schedule data depends on the Google Sheet; if it isn't reachable the app
falls back to built-in department lists and shows "график не опубликован".
