"""Хранение активных WebSocket-соединений в кэше.

Структура данных на комнату:

    {
        "channel_name": "username",
        ...
    }

В отличие от обычного module-level словаря, это работает
при нескольких workers/containers, если кэш общий (Redis).
"""

import json
import time

from django.core.cache import cache

ROOM_PRESENCE_KEY_TEMPLATE = "chat:online:{room_name}"
ROOM_PRESENCE_LOCK_TEMPLATE = "chat:online:lock:{room_name}"
RECONNECT_GRACE_KEY_TEMPLATE = "chat:online:grace:{room_name}:{username}"

PRESENCE_TTL = 60 * 60 * 24
LOCK_TIMEOUT = 5
LOCK_RETRIES = 3
LOCK_RETRY_DELAY = 0.05

# Grace-период после разрыва соединения. Если пользователь
# переподключается в течение этого окна (перезагрузка страницы,
# короткий сбой сети), мы не рассылаем пару сообщений
# "вышел из чата" / "вошёл в чат".
RECONNECT_GRACE = 5

# Метка "только что вышел" должна жить дольше, чем отложенная
# проверка ухода, чтобы не истечь раньше неё.
RECONNECT_GRACE_MARKER_TTL = RECONNECT_GRACE + 10


def _room_key(room_name):
    return ROOM_PRESENCE_KEY_TEMPLATE.format(room_name=room_name)


def _lock_key(room_name):
    return ROOM_PRESENCE_LOCK_TEMPLATE.format(room_name=room_name)


def _acquire_lock(room_name):
    # cache.add атомарен (и для ReddisCache, и для LocMemCache):
    # возвращает True, только если ключа ещё не было.
    return cache.add(
        _lock_key(room_name),
        "1",
        LOCK_TIMEOUT,
    )


def _release_lock(room_name):
    cache.delete(_lock_key(room_name))


def _with_lock(room_name, func):
    """Выполняет func внутри блокировки (с ограниченным числом попыток)."""

    for _ in range(LOCK_RETRIES):
        if _acquire_lock(room_name):
            try:
                return func()
            finally:
                _release_lock(room_name)

    # Не удалось взять блокировку — выполняем без неё.
    return func()


def get_online_users(room_name):
    """Возвращает {channel_name: username} для комнаты."""

    raw = cache.get(_room_key(room_name))

    if not raw:
        return {}

    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}


def get_online_usernames(room_name):
    """Возвращает отсортированный список уникальных имён онлайн."""

    users = get_online_users(room_name)
    return sorted(set(users.values()))


def add_online_user(room_name, channel_name, username):
    """Регистрирует соединение пользователя в комнате.

    Возвращает True, если у пользователя уже было активное
    соединение в комнате (переподключение или вторая вкладка).
    """

    state = {"was_online": False}

    def _add():
        users = get_online_users(room_name)

        state["was_online"] = (
            username in users.values()
        )

        users[channel_name] = username

        cache.set(
            _room_key(room_name),
            json.dumps(users),
            PRESENCE_TTL,
        )

    _with_lock(room_name, _add)

    return state["was_online"]


def _reconnect_key(room_name, username):
    return RECONNECT_GRACE_KEY_TEMPLATE.format(
        room_name=room_name,
        username=username,
    )


def mark_reconnect_grace(room_name, username):
    """Помечает, что пользователь только что разорвал соединение.

    Если он быстро вернётся — это переподключение, а не выход.
    """

    cache.set(
        _reconnect_key(room_name, username),
        "1",
        RECONNECT_GRACE_MARKER_TTL,
    )


def clear_reconnect_grace(room_name, username):
    """Снимает метку переподключения (пользователь вернулся)."""

    cache.delete(_reconnect_key(room_name, username))


def is_reconnect_within_grace(room_name, username):
    """Вернулся ли пользователь в течение grace-периода."""

    return bool(
        cache.get(_reconnect_key(room_name, username))
    )


def is_user_online(room_name, username):
    """Есть ли у пользователя активные соединения в комнате."""

    return username in get_online_users(room_name).values()


def remove_online_user(room_name, channel_name, username):
    """Убирает соединение.

    Возвращает кортеж (user_still_online, room_empty):
    есть ли у пользователя другие активные соединения в комнате
    и остался ли в комнате хоть кто-то онлайн.
    """

    def _remove():
        users = get_online_users(room_name)

        users.pop(channel_name, None)

        user_still_online = username in users.values()
        room_empty = not users

        if room_empty:
            cache.delete(_room_key(room_name))
        else:
            cache.set(
                _room_key(room_name),
                json.dumps(users),
                PRESENCE_TTL,
            )

        return user_still_online, room_empty

    return _with_lock(room_name, _remove)