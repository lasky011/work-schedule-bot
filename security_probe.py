"""
Пассивный security-probe Mini App API (без реальной атаки на пользователей).

Запуск:
    BASE_URL=https://work-schedule-bot.fly.dev python3 security_probe.py
"""

import json
import os
import sys
import urllib.error
import urllib.request

BASE_URL = os.getenv("BASE_URL", "https://work-schedule-bot.fly.dev").rstrip("/")
TIMEOUT = 15


def req(method: str, path: str, headers: dict | None = None, body: bytes | None = None) -> tuple[int, str]:
    url = f"{BASE_URL}{path}"
    request = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")[:2000]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")[:2000]


def check(name: str, ok: bool, detail: str):
    mark = "✅" if ok else "❌"
    print(f"{mark} {name}: {detail}")
    return ok


def main():
    passed = 0
    total = 0

    def run(name, ok, detail):
        nonlocal passed, total
        total += 1
        if check(name, ok, detail):
            passed += 1

    # 1. Protected endpoints without auth
    for path in (
        "/api/me",
        "/api/schedule/week",
        "/api/analytics",
        "/api/colleagues",
        "/api/team",
        "/api/shifts/day?date=2026-07-01",
    ):
        code, body = req("GET", path)
        run(f"no auth {path}", code == 401, f"HTTP {code}")

    # 2. Forged initData
    code, body = req(
        "GET",
        "/api/me",
        headers={"X-Telegram-Init-Data": "user=%7B%22id%22%3A1%7D&auth_date=9999999999&hash=0"},
    )
    run("forged initData", code == 401, f"HTTP {code}")

    # 3. POST shift without auth
    code, body = req(
        "POST",
        "/api/shifts",
        headers={"Content-Type": "application/json"},
        body=b'{"date":"2026-07-01","hours":8}',
    )
    run("POST /api/shifts no auth", code == 401, f"HTTP {code}")

    # 4. Health is public (expected) — check no secrets
    code, body = req("GET", "/api/health")
    health_ok = code == 200
    leaked = any(x in body.lower() for x in ("bot_token", "database_url", "password", "secret"))
    run("/api/health reachable", health_ok, f"HTTP {code}")
    run("/api/health no secrets", health_ok and not leaked, "ok" if not leaked else "possible leak")

    if health_ok:
        try:
            payload = json.loads(body)
            run(
                "health status field",
                payload.get("status") in {"ok", "degraded"},
                str(payload.get("status")),
            )
        except json.JSONDecodeError:
            run("health json", False, "invalid json")

    # 5. Static index without auth (expected)
    code, body = req("GET", "/")
    run("miniapp index public", code == 200, f"HTTP {code}")

    # 6. OpenAPI docs disabled
    code, _ = req("GET", "/docs")
    run("openapi /docs closed", code in (404, 405), f"HTTP {code}")

    # 7. Method confusion
    code, _ = req("DELETE", "/api/health")
    run("DELETE /api/health blocked", code in (404, 405, 401), f"HTTP {code}")

    print(f"\n{'✅' if passed == total else '⚠️'} Security probe: {passed}/{total} passed")
    if passed != total:
        sys.exit(1)


if __name__ == "__main__":
    main()
