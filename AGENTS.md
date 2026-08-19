# AGENTS.md

**Перед любой правкой продуктовой логики прочитай [`FORBIDDEN.md`](FORBIDDEN.md)** — там график ресторана, роли, управляющий и контракты, которые нельзя «улучшать» без явной просьбы.

## Cursor Cloud specific instructions

This repo is **TNG Alice** — a Python 3.12 Telegram bot for restaurant staff work-schedule
management. Three processes share one codebase: the main bot (`bot.py`), a FastAPI Mini App
(`api/app.py`, started in-process by `bot.py` when `MINIAPP_ENABLED` is set), and an admin bot
(`admin_bot.py`). Lint/test is `make check` (`smoke_test.py` mocks DB/Telegram/Sheets).

### Test vs prod Fly apps
- Prod: `fly.toml` → app `work-schedule-bot` — **do not deploy here unless explicitly asked**.
- Test: `fly.test.toml` → app `work-schedule-bot-test` (org `personal`, region `fra`).
- Admin: `fly.admin.toml` → app `work-schedule-bot-admin`.

The test app already exists and has secrets (`BOT_TOKEN`, `DATABASE_URL`, `MINIAPP_ENABLED`,
`MINIAPP_URL`, etc.). `fly deploy` does **not** create an app; if `Could not find App` appears,
the local `fly` CLI is almost certainly logged into a different org/account than `personal`.

### Deploying a branch to the test bot
Needs `FLY_API_TOKEN` in the environment (deploy-scoped token is enough) and `flyctl`
(`curl -fsSL https://fly.io/install.sh | sh`, then `export PATH="$HOME/.fly/bin:$PATH"`).

From the repo root, on the branch to ship:

```
flyctl deploy -c fly.test.toml --remote-only
```

Schema updates (including `users.onboarding_seen`) are applied on boot by `init_db()` in
`bot.py`; no separate migration step is required. Health: `https://work-schedule-bot-test.fly.dev/api/health`.

To reset Mini App onboarding so it shows again for every test user:

```
flyctl ssh console -a work-schedule-bot-test -C "python3 -c \"
from db import get_db_connection
conn = get_db_connection(); cur = conn.cursor()
cur.execute('UPDATE users SET onboarding_seen = 0')
conn.commit(); print('reset', cur.rowcount)
cur.close(); conn.close()
\""
```

Then reopen the **test** bot Mini App (URL `https://work-schedule-bot-test.fly.dev`).

### Supervisor Mini App
Managers listed in `SUPERVISOR_NAMES` (or with role `Управляющий`) use the **fixed weekly schedule** in `services/supervisor_schedule.py`. Do **not** look their shifts up in Google Sheets. Waiter «Владислав» is a different person — never alias. GitHub `main` currently does not contain commit `dfbe8f0`; the module was recovered from Fly prod. Personal hours: Mon/Wed 11–19, Tue meeting 11–13 + shift 16–19, Thu/Sun off, Fri/Sat 16–01. Mini App tabs: schedule / team / people only.
