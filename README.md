# Project CHAT

Самохостимый веб-чат на Django + Channels (WebSocket) с комнатами, личными
переписками, реакциями, голосовыми сообщениями и загрузкой медиа.

## Возможности

- Регистрация, вход и профиль пользователя (`users`).
- Комнаты: создание, изменение, вступление/выход, управление участниками
  (владелец), поиск по комнатам и контактам в сайдбаре.
- Личные (прямые) переписки с пользователями.
- Сообщения в реальном времени по WebSocket:
  - отправка и история,
  - редактирование и удаление своих сообщений,
  - пересылка,
  - ответы на сообщения,
  - реакции смайлами,
  - голосовые сообщения,
  - загрузка файлов/медиа и просмотр медиа комнаты.
- Статусы «онлайн» и счётчики непрочитанных сообщений.
- Адаптивная вёрстка для десктопов, планшетов и телефонов.
- Тёмная тема.

## Технологии

| Слой | Стек |
|---|---|
| Backend | Python 3.14, Django 6.1, PostgreSQL 17 |
| Realtime | Django Channels 4, Daphne (ASGI), Redis |
| Frontend | Vanilla JS, собственный CSS, emoji-SVG-иконки |
| Инфраструктура | Docker Compose: nginx + web + redis + postgres, Poetry |

## Структура проекта

```text
config/            Конфигурация Django (settings, urls, asgi/wsgi)
chat/              Основное приложение чата
  consumers.py     WebSocket-контроллер
  models.py        Модели комнат, сообщений, реакций и др.
  views.py         HTTP/JSON-эндпоинты
  attachments.py   Защищённая выдача вложений
  urls.py          HTTP-маршруты
  routing.py       WebSocket-роутинг
  management/commands/seed_initial.py   Стартовые данные
users/             Пользователи, профиль, auth и rate limiting
static/chat/       CSS и JavaScript чата
templates/         Общие шаблоны
media/             Пользовательские файлы
staticfiles/       Собранная статика
docker-compose.yaml  Docker Compose стек
```

## Конфигурация

Создайте `.env` из `.env.example` и замените примерные значения реальными.

Обязательные для обычного запуска параметры:

- `SECRET_KEY` — секретный ключ Django;
- `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` — PostgreSQL;
- `ALLOWED_HOSTS` и `CSRF_TRUSTED_ORIGINS` — разрешённые адреса приложения.

На **пустой базе** команда `seed_initial` требует также явные
`SEED_ADMIN_USERNAME` и `SEED_ADMIN_PASSWORD`. Пароль должен проходить
стандартные валидаторы Django. Предсказуемых значений по умолчанию нет.

Полный пример находится в `.env.example`.

## Локальный запуск без Docker

Нужны Python 3.14, Poetry и доступный PostgreSQL 17. Redis для одиночного
локального процесса необязателен: без `USE_REDIS_CHANNEL_LAYER=True` Django
использует in-memory cache/channel layer.

```bash
poetry install
cp .env.example .env

poetry run python manage.py migrate
poetry run python manage.py seed_initial
poetry run daphne -b 0.0.0.0 -p 8000 config.asgi:application
```

Перед `seed_initial` на пустой БД задайте в `.env` безопасные
`SEED_ADMIN_USERNAME` и `SEED_ADMIN_PASSWORD`.

Для локальной разработки можно использовать:

```bash
poetry run python manage.py runserver
```

## Запуск через Docker Compose

Docker Compose поднимает:

- `postgres` — PostgreSQL 17;
- `redis` — общий cache/channel layer;
- `web` — migrate → seed_initial → collectstatic → Daphne;
- `nginx` — reverse proxy на порту `8000`.

```bash
cp .env.example .env
# Заполните SECRET_KEY, DB_PASSWORD и seed credentials для пустой БД.
docker compose up -d --build
```

После запуска приложение доступно по адресу `http://127.0.0.1:8000/`.

PostgreSQL хранит данные в Docker volume `postgres_data`. Пользовательские
файлы и собранная статика монтируются из `./media` и `./staticfiles`.

В Docker Compose автоматически включаются:

- `USE_REDIS_CHANNEL_LAYER=True`;
- `USE_NGINX_PROTECTED_MEDIA=True`;
- `TRUST_PROXY_CLIENT_IP=True`.

Последний параметр безопасен в штатной схеме, потому что nginx перезаписывает
`X-Forwarded-For` фактическим адресом подключившегося клиента.

## Вложения

Файлы сообщений не должны отдаваться напрямую через nginx. URL вида
`/media/chat_files/...` сначала проходит проверку авторизации и членства в
комнате в Django, после чего nginx получает внутренний `X-Accel-Redirect`.
Остальной `/media/` остаётся обычной статической раздачей.

## Переменные окружения

| Переменная | Значение по умолчанию | Назначение |
|---|---|---|
| `SECRET_KEY` | нет | Обязательный секретный ключ Django |
| `DEBUG` | `False` | Режим отладки |
| `ALLOWED_HOSTS` | `127.0.0.1,localhost,[::1]` | Разрешённые хосты |
| `CSRF_TRUSTED_ORIGINS` | локальные адреса | Доверенные CSRF origins |
| `DB_NAME` | `project_chat` | Имя PostgreSQL БД |
| `DB_USER` | `project_chat` | Пользователь PostgreSQL |
| `DB_PASSWORD` | пусто в Django / обязательно в Compose | Пароль PostgreSQL |
| `DB_HOST` | `localhost` | Хост PostgreSQL; в Compose переопределён на `postgres` |
| `DB_PORT` | `5432` | Порт PostgreSQL |
| `REDIS_HOST` / `REDIS_PORT` | `localhost` / `6379` | Redis |
| `USE_REDIS_CHANNEL_LAYER` | `False` | Redis для cache/channel layer |
| `USE_NGINX_PROTECTED_MEDIA` | `False` | Отдача chat-вложений через X-Accel-Redirect |
| `TRUST_PROXY_CLIENT_IP` | `False` | Разрешить доверять proxy IP после нормализации nginx |
| `USE_HTTPS` | `False` | HSTS, secure cookies и HTTPS redirect |
| `SEED_ADMIN_USERNAME` | нет | Имя начального пользователя пустой БД |
| `SEED_ADMIN_PASSWORD` | нет | Сильный пароль начального пользователя |

## WebSocket

Endpoint комнаты:

```text
ws://<host>/ws/chat/<room>/
```

Подключение и отправка сообщений разрешены только участникам комнаты.

Основные входящие типы JSON-сообщений:

| Тип | Назначение |
|---|---|
| `comment` | Текстовое сообщение |
| `react` | Поставить/снять реакцию |
| `ping` | Heartbeat |

Основные исходящие события:

| Тип | Назначение |
|---|---|
| `history` | История сообщений при подключении |
| `chat_message` | Новое сообщение |
| `message_updated` / `message_deleted` | Редактирование / удаление |
| `message_reaction` | Изменение реакции |
| `user_status` | Статус участника |
| `online_users` | Список онлайн-участников |
| `unread_update` | Изменение счётчика непрочитанных |

Загрузка файлов выполняется отдельным HTTP endpoint комнаты, а затем событие
сообщения распространяется через channel layer.

## Тесты

Для локальной проверки всего Django test suite:

```bash
poetry run python manage.py test --settings=config.settings_test --noinput
```

В Docker для параллельно живущей PostgreSQL среды используйте отдельное имя
тестовой БД на каждый запуск, чтобы исключить коллизии между test runners.

Пример для PowerShell:

```powershell
$testDb = "project_chat_test_" + ([guid]::NewGuid().ToString("N").Substring(0,8))
docker compose run --rm -e "DB_NAME=$testDb" web python manage.py test --settings=config.settings_test --noinput
```

Дополнительные проверки:

```bash
node --check static/chat/js/chat.js
poetry run flake8
```

Перед фиксацией изменений также полезно выполнить:

```bash
git diff --check
```
