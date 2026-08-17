-- Past sheet names for the same person (Анна / Аня / Анна 2-2 утро).
CREATE TABLE IF NOT EXISTS public.person_name_aliases (
    id          SERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL,
    alias       TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, alias)
);

CREATE INDEX IF NOT EXISTS person_name_aliases_alias_idx
    ON public.person_name_aliases (alias);

COMMENT ON TABLE public.person_name_aliases IS
    'Former Google Sheet names kept so schedule lookup works across periods';
