"""Amvera entrypoint: staff bot + admin bot in one container."""

from __future__ import annotations

import signal
import subprocess
import sys
import time

PROCS: list[subprocess.Popen] = []


def _stop(_signum=None, _frame=None) -> None:
    for proc in PROCS:
        if proc.poll() is None:
            proc.terminate()
    for proc in PROCS:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    sys.exit(0)


def main() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    bot = subprocess.Popen([sys.executable, "bot.py"])
    admin = subprocess.Popen([sys.executable, "admin_bot.py"])
    PROCS.extend((bot, admin))

    while True:
        if bot.poll() is not None:
            print("bot.py exited, stopping admin_bot.py", flush=True)
            _stop()
        if admin.poll() is not None:
            print("admin_bot.py exited, stopping bot.py", flush=True)
            _stop()
        time.sleep(2)


if __name__ == "__main__":
    main()
