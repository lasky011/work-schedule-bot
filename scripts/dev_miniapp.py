#!/usr/bin/env python3
"""Local Mini App for development.

Uses sqlite (users.db) when DATABASE_URL is unset. Does not start Telegram
polling, so it is safe to run next to a production bot.

    python3 scripts/dev_miniapp.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if not os.environ.get("BOT_TOKEN"):
    os.environ["BOT_TOKEN"] = "local-dev-token"
    print("BOT_TOKEN unset; Mini App auth uses local-dev-token (not a Telegram bot)")

os.environ.setdefault("MINIAPP_ENABLED", "true")
os.environ.setdefault("MINIAPP_PORT", "8080")


def _init_sqlite() -> None:
    import app_config

    # bot.py imports validate_required_env and refuses to load without DATABASE_URL.
    # Patch before that import so the sqlite fallback in db.py stays available.
    app_config.validate_required_env = lambda: None
    import bot

    bot.init_db()
    print(f"sqlite schema ready: {ROOT / 'users.db'}")


def main() -> None:
    if os.environ.get("DATABASE_URL"):
        print("DATABASE_URL is set; Mini App will use Postgres")
    else:
        _init_sqlite()

    import uvicorn
    from api.app import create_app

    port = int(os.environ.get("MINIAPP_PORT") or os.environ.get("PORT") or "8080")
    print(f"Mini App http://127.0.0.1:{port}/  health: /api/health")
    uvicorn.run(create_app(), host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
