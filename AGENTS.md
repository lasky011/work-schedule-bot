# work-schedule-bot

Python Telegram bots (aiogram, long polling) plus a Mini App served from the staff bot.

- Staff: `python3 bot.py` (polling, notifications, Mini App on `MINIAPP_PORT`)
- Admin: `python3 admin_bot.py` (polling, no HTTP)
- Tests: `python3 smoke_test.py` or `make check`

Do not run two processes with the same `BOT_TOKEN`. Prod and test must use different tokens.

## Cursor Cloud specific instructions

Hosting is **not Fly-first** anymore. Fly apps may still be running until the ruble host is live; do not deploy to Fly unless asked.

New deploys: cheapest always-on is **Amvera «Начальный» ~290 ₽** (upgrade to 1 GB / 490 ₽ if OOM); 1 GB DIY is **4VPS EU ~420 ₽**. Timeweb Apps ~510 ₽. Runbook: `deploy/README.md`. **Vercel cannot host these bots** (long polling + in-process notify loops).

Postgres is Supabase (`DATABASE_URL`). Google Sheets is public CSV, no service account.

Mini App Telegram WebApp needs a public HTTPS `MINIAPP_URL`. Health: `GET /api/health` on the staff bot.

Notification loops live in `bot.py` and die if the process sleeps. Always-on hosting only.
