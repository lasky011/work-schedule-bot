#!/bin/sh
# One container: staff bot (polling + Mini App) and admin bot.
# Used by Amvera. docker-compose runs the two processes as separate services instead.
set -eu

bot_pid=""
admin_pid=""

term() {
  if [ -n "$bot_pid" ]; then kill "$bot_pid" 2>/dev/null || true; fi
  if [ -n "$admin_pid" ]; then kill "$admin_pid" 2>/dev/null || true; fi
  wait || true
  exit 0
}

trap term TERM INT

python3 bot.py &
bot_pid=$!
python3 admin_bot.py &
admin_pid=$!

while true; do
  if ! kill -0 "$bot_pid" 2>/dev/null; then
    echo "bot.py exited, stopping admin_bot.py"
    kill "$admin_pid" 2>/dev/null || true
    wait "$bot_pid" || true
    exit 1
  fi
  if ! kill -0 "$admin_pid" 2>/dev/null; then
    echo "admin_bot.py exited, stopping bot.py"
    kill "$bot_pid" 2>/dev/null || true
    wait "$admin_pid" || true
    exit 1
  fi
  sleep 2
done
