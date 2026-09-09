# Project CHAT

Самохостимый веб-чат на Django + Channels (WebSocket) с комнатами, личными
переписками, реакциями, голосовыми сообщениями и загрузкой медиа.

## Возможности

- Регистрация, вход, профиль пользователя (`users`).
- Комнаты: создание, изменение, вступление/выход, управление участниками
  (владелец), поиск по комнатам и контактам в сайдбаре.
- Личные (прямые) переписки с пользователями.
- Сообщения в реальном времени по WebSocket:
  - отправка и история,
  - редактирование и удаление своих сообщений,
  - пересылка (одиночная и из режима выбора),
  - режим выбора сообщений (клик — выделить/снять, копировать, переслать,
    удалить только свои),
  - ответы на сообщения,
  - реакции смайлами,
  - голосовые сообщения (запись с зажатой кнопкой),
  - загрузка файлов/медиа и просмотр медиа комнаты.
- Статусы «онлайн», счётчики непрочитанных сообщений (обновляются через
  WebSocket).
- Адаптивная вёрстка: десктоп, планшеты и телефоны (сайдбар на мобильных
  сворачивается по умолчанию, учтены безопасные зоны iOS и `100dvh`).
- Тёмная тема «из коробки».

## Технологии

| Слой | Стек |
|---|---|
| Backend | Python 3.14, Django 6.1, SQLite (WAL) |
| Realtime | Django Channels 4, Daphne (ASGI), Redis (опционально) |
| Frontend | Vanilla JS (ES), собственный CSS, emoji-SVG-иконки |
| Инфраструктура | Docker Compose (web + nginx + redis), Poetry |

## Структура проекта

```
config/            Конфигурация Django (settings, urls, asgi/wsgi)
chat/              Основное приложение чата:
  consumers.py     WebSocket-контроллер (ChatConsumer)
  models.py        ChatRoom, Message, Reaction, VoiceMessage, ...
  views.py         HTTP/JSON-эндпоинты (CRUD, пересылка, медиа, участники)
  urls.py          Маршруты
  routing.py       WebSocket-роутинг (ws/chat/<room>/)
  tests.py         Тесты (включая WebSocket-коммуникатор)
  management/commands/seed_initial.py   Стартовые данные
users/             Настраиваемая модель пользователя, профиль, auth-шаблоны
static/chat/       CSS и JS чата
templates/         Общие шаблоны
media/ staticfiles/  Пользовательские файлы и собранная статика
docker-compose.yaml  Производственный запуск (web/nginx/redis)
```

## Локальный запуск

Предварительно: [Poetry](https://python-poetry.org/) и (для производственного
стека) запущенный Redis на `localhost:6379`.

```bash
# 1. Зависимости
poetry install

# 2. Конфигурация
cp .env.example .env
# Обязательно задайте SECRET_KEY и, при необходимости, DEBUG=True для разработки.

# 3. БД и стартовые данные
poetry run python -u manage.py migrate
poetry run python -u manage.py seed_initial   # admin/admin, комната general

# 4. Запуск ASGI-сервера (нужен для WebSocket)
poetry run daphne -b 0.0.0.0 -p 8000 config.asgi:application
```

Откройте http://127.0.0.1:8000/ — произойдёт редирект на первую комнату.

> Для разработки можно использовать `poetry run python -u manage.py runserver`
> (Django умеет runserver поверх ASGI при установленном daphne), но WebSocket
> надёжнее проверять через daphne.

### Redis

- По умолчанию канал WebSocket работает в памяти (`InMemoryChannelLayer`) —
  достаточно для одного процесса.
- Для масштабирования (несколько процессов/воркеров, Docker) включите
  `USE_REDIS_CHANNEL_LAYER=True`: каналы и кэш переедут на Redis.

## Docker

```bash
cp .env.example .env   # заполните SECRET_KEY
docker compose up -d --build
```

Сервисы: `web` (migrate → seed_initial → collectstatic → daphne), `redis`,
`nginx` (порт `8000`). Данные в томах `./db`, `./media`, `./staticfiles`.

## Переменные окружения

Полный набор — в [.env.example](.env.example).

| Переменная | По умолчанию | Описание |
|---|---|---|
| `SECRET_KEY` | — | Обязательная секретная ключ-строка |
| `DEBUG` | `False` | Режим отладки (`True`) |
| `ALLOWED_HOSTS` | `127.0.0.1,localhost,[::1]` | Разрешённые хосты через запятую |
| `CSRF_TRUSTED_ORIGINS` | `http://127.0.0.1:8000,http://localhost:8000` | Доверенные origins |
| `REDIS_HOST` / `REDIS_PORT` | `localhost` / `6379` | Redis для каналов/кэша |
| `USE_REDIS_CHANNEL_LAYER` | `False` | Использовать Redis для WebSocket/кэша |
| `USE_HTTPS` | `False` | HSTS, secure-cookies, редирект на HTTPS |
| `EMAIL_BACKEND` | консоль | SMTP: `django.core.mail.backends.smtp.EmailBackend` |
| `SEED_ADMIN_USERNAME` / `SEED_ADMIN_PASSWORD` | `admin` / `admin` | Стартовый пользователь на пустой БД |
| `DB_PATH` | `./db.sqlite3` | Путь к файлу SQLite |

## Протокол WebSocket

Лимит — `ws://<host>/ws/chat/<room>/` (уровень доступа: только участники).

Входящие сообщения (объекты JSON):

| Тип | Назначение |
|---|---|
| `comment` | Публикация текстового сообщения |
| `media` | Публикация загрузки файла (сообщение с вложениями) |
| `react` | Поставить/снять реакцию |
| `ping` | Heartbeat |

Исходящие события:

| Тип | Назначение |
|---|---|
| `history` | История сообщений при подключении |
| `chat_message` | Новое сообщение |
| `message_updated` / `message_deleted` | Правка / удаление сообщения |
| `message_reaction` | Реакция добавлена/снята |
| `user_status` | Вход/выход участника |
| `online_users` | Актуальный список онлайн-участников |
| `unread_update` | Изменение счётчиков непрочитанного |

## Тесты и линтеры

```bash
# Тесты приложения chat (включая WebSocket-интеграцию)
poetry run python -u manage.py test chat

# Проверка JS
node --check static/chat/js/chat.js

# Линтеры Python (flake8/black/isort настроены в pyproject.toml)
poetry run flake8
```

Известное замечание: тесты прямых переписок используют `ALLOWED_HOSTS` из
`.env`; убедитесь, что там есть `localhost`, иначе часть DM-тестов даст 400.