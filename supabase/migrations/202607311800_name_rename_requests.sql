-- Manual confirmation when a sheet person name changes (Анна → Анна 2-2 утро).
CREATE TABLE IF NOT EXISTS public.name_rename_requests (
    id            SERIAL PRIMARY KEY,
    user_id       BIGINT NOT NULL,
    old_name      TEXT NOT NULL,
    new_name      TEXT NOT NULL,
    role          TEXT,
    status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'confirmed', 'rejected')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at   TIMESTAMPTZ,
    resolved_by   BIGINT
);

CREATE UNIQUE INDEX IF NOT EXISTS name_rename_requests_pending_uidx
    ON public.name_rename_requests (user_id, old_name, new_name)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS name_rename_requests_status_idx
    ON public.name_rename_requests (status, created_at DESC);

COMMENT ON TABLE public.name_rename_requests IS
    'Pending/resolved sheet name renames awaiting admin confirmation';
