CREATE TABLE IF NOT EXISTS public.role_rates (
    role_key    TEXT PRIMARY KEY,
    rate        INTEGER NOT NULL CHECK (rate >= 0),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.role_rates IS 'Hourly pay rates by role (RUB/hour)';
