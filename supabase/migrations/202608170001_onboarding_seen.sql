-- Флаг «пользователь прошёл онбординг в Mini App».
-- 0 — не проходил (показываем приветствие/тур), 1 — прошёл или пропустил.
ALTER TABLE users ADD COLUMN IF NOT EXISTS onboarding_seen INTEGER DEFAULT 0;

COMMENT ON COLUMN users.onboarding_seen IS 'Mini App onboarding completed/skipped (0/1)';
