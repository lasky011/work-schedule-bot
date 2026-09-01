-- Manual gen-cleaning days per month + notify-once lock.

CREATE TABLE IF NOT EXISTS public.gen_cleaning_month_overrides (
    year INT NOT NULL CHECK (year BETWEEN 2000 AND 2100),
    month INT NOT NULL CHECK (month BETWEEN 1 AND 12),
    days INT[] NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (year, month)
);

COMMENT ON TABLE public.gen_cleaning_month_overrides IS
    'If a month row exists, gen cleaning uses these days instead of every-other-Wednesday cadence';

CREATE TABLE IF NOT EXISTS public.gen_cleaning_notify_sent (
    cleaning_day DATE PRIMARY KEY,
    sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.gen_cleaning_notify_sent IS
    'Eve reminder already sent for this cleaning day (shared by main/test bots)';
