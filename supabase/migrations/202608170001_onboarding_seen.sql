-- Флаг «пользователь прошёл онбординг в Mini App».
-- 0 — не проходил (показываем приветствие/тур), 1 — прошёл или пропустил.
ALTER TABLE users ADD COLUMN IF NOT EXISTS onboarding_seen INTEGER DEFAULT 0;

COMMENT ON COLUMN users.onboarding_seen IS 'Mini App onboarding completed/skipped (0/1)';

-- Уже пользуются ботом — экскурсию не показываем.
UPDATE users
SET onboarding_seen = 1
WHERE COALESCE(onboarding_seen, 0) = 0
  AND name IS NOT NULL AND TRIM(name) != '';
