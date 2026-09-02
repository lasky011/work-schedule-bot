# Хостинг без Fly.io

Боты ходят в Telegram long polling и шлют напоминания по часам. Их нельзя класть на «засыпающий» бесплатный тариф (Render/Railway free, облачные функции без cron). Бесплатно 24/7 почти нет: у Amvera дают ~111 ₽ на старт, этого хватает на несколько дней.

База остаётся в Supabase (`DATABASE_URL`) — её не переносим. Google Таблица по-прежнему читается по публичному CSV.

## Что выбрать (оплата в рублях)

| Вариант | Цена | Зачем |
|---|---|---|
| **Amvera Cloud** (рекомендую) | ~490 ₽/мес, тариф «Начальный Плюс» 1 ГБ | Карта РФ / СБП, не засыпает, регион Варшава, HTTPS для Mini App |
| Timeweb Apps + этот `docker-compose.yml` | от ~400–700 ₽ за маленькую ВМ | GitHub-деплой, SSL на первом сервисе `bot` |
| Любой VPS в ЕС (4VPS, Selectel NL, Aeza) | от ~150–300 ₽ | `docker compose up -d`, сами ставите HTTPS |

Не бери чистый российский VPS без прокси: Telegram Bot API часто недоступен. Amvera из Москвы проксирует Telegram сама, но для стабильности лучше **Варшава**.

Тестовый бот (`work-schedule-bot-test`) на новый хост не переносим: это вторая копия того же кода с другим токеном, она только жрёт деньги.

## Amvera — шаги

1. Регистрация: https://amvera.ru (приветственные 111 ₽).
2. Новое приложение из GitHub `lasky011/work-schedule-bot`, ветка `main` (или эта, пока PR не влит).
3. Регион **Warsaw**. Тариф **Начальный Плюс (1 GB)**. Пробный 100 МБ не хватит на два процесса.
4. В переменных окружения скопируй ключи из `.env.example`. `MINIAPP_ENABLED=true`, `MINIAPP_PORT=8080`.
5. Сборка подхватит `amvera.yaml`: оба бота в одном контейнере, Mini App на 8080.
6. После старта возьми HTTPS-домен Amvera и пропиши его в `MINIAPP_URL` (без слэша в конце), пересобери.
7. Проверка: `GET https://<домен>/api/health`, затем напиши штатному боту и админ-боту.
8. Когда новое место отвечает, **выключи Fly**, иначе два процесса с одним токеном будут отбирать друг у друга апдейты:

```bash
flyctl scale count 0 -a work-schedule-bot
flyctl scale count 0 -a work-schedule-bot-admin
flyctl scale count 0 -a work-schedule-bot-test
```

Приложения можно удалить позже: `flyctl apps destroy <name>`.

## Timeweb Apps / VPS

В корне уже есть `docker-compose.yml`. Первый сервис `bot` получит HTTPS-домен Timeweb — его и пиши в `MINIAPP_URL`.

```bash
cp .env.example .env   # заполни токены
docker compose up -d --build
curl -sS http://127.0.0.1:8080/api/health
```

На Timeweb не используй host-порты 80/443 и не добавляй `volumes` — платформа это запрещает.

## Переменные

Обязательные: `BOT_TOKEN`, `DATABASE_URL`, `ADMIN_BOT_TOKEN`, `ADMIN_IDS`.
Для Mini App: `MINIAPP_ENABLED`, `MINIAPP_PORT`, `MINIAPP_URL`.

Админ-бот тоже должен знать `BOT_TOKEN` — рассылки сотрудникам идут от штатного бота.
