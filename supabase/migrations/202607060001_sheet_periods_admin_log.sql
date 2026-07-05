-- Core tables for schedule bot (idempotent).

CREATE TABLE IF NOT EXISTS public.sheet_periods (
    id          SERIAL PRIMARY KEY,
    year        INT NOT NULL,
    month       INT NOT NULL CHECK (month BETWEEN 1 AND 12),
    start_day   INT NOT NULL CHECK (start_day IN (1, 16)),
    gid         TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (year, month, start_day)
);

COMMENT ON TABLE public.sheet_periods IS 'Google Sheets gid for schedule half-month periods';

CREATE TABLE IF NOT EXISTS public.admin_log (
    id              SERIAL PRIMARY KEY,
    admin_user_id   BIGINT NOT NULL,
    action          TEXT NOT NULL,
    details         TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.admin_log IS 'Admin bot action audit trail';
