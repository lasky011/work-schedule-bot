"""Rewrite Supabase direct DSNs to the IPv4 session pooler."""

import logging
import os
from urllib.parse import quote, unquote, urlparse, urlunparse

_DEFAULT_POOLER_HOST = os.getenv(
    "SUPABASE_POOLER_HOST",
    "aws-1-eu-central-1.pooler.supabase.com",
)


def postgres_dsn(raw: str | None) -> str | None:
    """Use Supabase session pooler (IPv4) instead of direct db.* IPv6 host."""
    if not raw:
        return raw
    parsed = urlparse(raw.strip())
    host = parsed.hostname or ""
    if not (host.startswith("db.") and host.endswith(".supabase.co")):
        return raw
    ref = host.removeprefix("db.").removesuffix(".supabase.co")
    user = unquote(parsed.username or "postgres")
    if "." not in user:
        user = f"{user}.{ref}"
    password = unquote(parsed.password or "")
    port = parsed.port or 5432
    query = parsed.query
    if "sslmode=" not in query:
        query = f"{query}&sslmode=require" if query else "sslmode=require"
    netloc = f"{quote(user, safe='.')}:{quote(password, safe='')}@{_DEFAULT_POOLER_HOST}:{port}"
    rewritten = urlunparse(parsed._replace(netloc=netloc, query=query))
    logging.info("postgres: using session pooler %s user=%s", _DEFAULT_POOLER_HOST, user)
    return rewritten
