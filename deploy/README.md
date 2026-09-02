# Хостинг без Fly.io

Боты ходят в Telegram long polling и шлют напоминания по часам. Их нельзя класть на «засыпающий» бесплатный тариф (Render/Railway free, облачные функции без cron). Бесплатно 24/7 почти нет: у Amvera дают ~111 ₽ на старт, этого хватает на несколько дней.

База остаётся в Supabase (`DATABASE_URL`) — её не переносим. Google Таблица по-прежнему читается по публичному CSV.

## Vercel — нет

Vercel крутит короткие serverless-функции (на Hobby максимум ~5 минут на запрос), а не вечный процесс. Наш код делает `start_polling()` и держит циклы уведомлений внутри `bot.py`. На Vercel это не запустится: функция умрёт, polling отвалится, «завтра ген уборка в 22:00» не уйдёт.

Чтобы жить на Vercel, нужно переписывать оба бота на webhook + внешний cron и выносить Mini App API отдельно. Это другой проект. Оплата у Vercel в долларах, не в рублях.

Статику Mini App тоже нельзя просто «выложить на Vercel»: расписание идёт с того же FastAPI, что и бот.

## Что выбрать (оплата в рублях)

| Вариант | Цена | Зачем |
|---|---|---|
| **Timeweb Apps** (Docker / Compose) | Backend App ~1 CPU / 1 ГБ ≈ **510 ₽/мес** | СБП и карта РФ, регион **AMS-1 или FRA-1**, бесплатный SSL, GitHub-деплой |
| **Amvera Cloud** | ~490 ₽/мес, «Начальный Плюс» 1 ГБ | Тоже карта РФ, Варшава, оба бота одним контейнером |
| Любой VPS в ЕС (4VPS, Selectel NL, Aeza) | от ~150–300 ₽ | `docker compose up -d`, HTTPS сами |

Не бери фронтенд-тариф Timeweb «от 1 ₽» и не ставь ботов в SPB/MSK: это биллинг за HTTP-запросы / российский IP. Telegram Bot API нужен европейский регион.

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

## Timeweb Apps

1. https://timeweb.cloud/services/apps — тип **Docker**. Если в панели есть вкладка **Docker Compose**, бери её: в корне репозитория уже `docker-compose.yml` (первый сервис `bot` получит HTTPS-домен).
2. Если Compose в панели нет (на маркетинговой странице ещё пишут, что «не читает compose») — тип **Dockerfile**, команда запуска `sh deploy/run-both.sh`.
3. Регион **AMS-1 (Амстердам)** или **FRA-1 (Франкфурт)**, не Москва/Питер.
4. Конфиг около **1 CPU / 1 ГБ RAM** (два процесса Python). Меньше 1 ГБ лучше не брать.
5. Переменные из `.env.example`. `MINIAPP_ENABLED=true`, `MINIAPP_PORT=8080`.
6. После деплоя технический домен Timeweb → в `MINIAPP_URL`, перезапуск.
7. Проверка: `GET https://<домен>/api/health`, затем штатный и админ-бот в Telegram.
8. Остановить Fly, иначе два polling с одним токеном начнут конфликтовать (команды выше).

На Timeweb Compose нельзя: host-порты 80/443 и директива `volumes`.

## VPS (в том числе Timeweb Cloud server)

```bash
cp .env.example .env   # заполни токены
docker compose up -d --build
curl -sS http://127.0.0.1:8080/api/health
```

## Переменные

Обязательные: `BOT_TOKEN`, `DATABASE_URL`, `ADMIN_BOT_TOKEN`, `ADMIN_IDS`.
Для Mini App: `MINIAPP_ENABLED`, `MINIAPP_PORT`, `MINIAPP_URL`.

Админ-бот тоже должен знать `BOT_TOKEN` — рассылки сотрудникам идут от штатного бота.
