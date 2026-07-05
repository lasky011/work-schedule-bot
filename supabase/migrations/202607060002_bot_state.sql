-- Signal table: admin bumps sheet_cache_version, main/test bots react within minutes.

CREATE TABLE IF NOT EXISTS public.bot_state (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.bot_state IS 'Cross-process bot coordination (cache refresh signals)';
