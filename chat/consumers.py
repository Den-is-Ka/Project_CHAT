import asyncio
import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from . import notifications
from .models import (
    REACTION_EMOJIS,
    ChatRoom,
    Message,
    MessageReaction,
)
from .presence import (
    RECONNECT_GRACE,
    add_online_user,
    clear_reconnect_grace,
    get_online_usernames,
    is_reconnect_within_grace,
    is_user_online,
    mark_reconnect_grace,
    remove_online_user,
)
from .rate_limit import rate_limit_allows
from .utils import serialize_message
from .validators import validate_message

# Коды закрытия WebSocket по причинам:
# 4000 — комната не найдена,
# 4001 — нет доступа к комнате.
CLOSE_ROOM_NOT_FOUND = 4000
CLOSE_ACCESS_DENIED = 4001

# Ограничение частоты отправки сообщений:
# не более SEND_RATE_LIMIT сообщений за окно SEND_RATE_WINDOW секунд.
SEND_RATE_LIMIT = 10
SEND_RATE_WINDOW = 5

# Сколько последних сообщений отдаётся при подключении.
MESSAGE_HISTORY_LIMIT = 50


class ChatConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer для чата."""

    async def connect(self):
        """Подключение пользователя к комнате."""

        user = self.scope["user"]

        # Анонимным пользователям доступ к WebSocket запрещён.
        if user.is_anonymous:
            await self.close(code=CLOSE_ACCESS_DENIED)
            return

        self.room_name = self.scope["url_route"]["kwargs"]["room_name"]

        # Получаем комнату.
        self.room = await self.get_room(self.room_name)

        if self.room is None:
            await self.close(code=CLOSE_ROOM_NOT_FOUND)
            return

        # Проверяем доступ пользователя к комнате.
        if not await self.has_room_access(self.room):
            await self.close(code=CLOSE_ACCESS_DENIED)
            return

        # Группа комнаты.
        self.room_group_name = f"chat_{self.room.id}"

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name,
        )

        # Личный канал пользователя: сюда приходят события
        # о непрочитанных сообщениях в других комнатах.
        self.user_group_name = f"user_{user.id}"

        await self.channel_layer.group_add(
            self.user_group_name,
            self.channel_name,
        )

        await self.accept()

        # Регистрируем пользователя как онлайн. Если у него уже
        # было активное соединение в комнате или он быстро вернулся
        # после разрыва (перезагрузка страницы, флап сети) —
        # считаем это переподключением и не анонсируем вход заново.
        user_was_online = await self.presence_add(
            self.channel_name,
            user.username,
        )

        reconnecting = user_was_online or await self.presence_reconnect_grace(user.username)

        if reconnecting:
            await self.presence_clear_grace(user.username)

        # Сообщаем остальным участникам о входе.
        if not reconnecting:
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "user_status",
                    "action": "join",
                    "username": user.username,
                    "channel_name": self.channel_name,
                },
            )

        # Обновляем список онлайн-пользователей.
        await self.broadcast_online_users()

        # Отправляем историю сообщений подключившемуся пользователю.
        await self.send_message_history()

    async def disconnect(self, close_code):
        """Отключение пользователя от комнаты."""

        if not hasattr(self, "room_group_name"):
            return

        user = self.scope["user"]

        if not user.is_anonymous:
            user_still_online, _ = await self.presence_remove(
                self.channel_name,
                user.username,
            )

            # Если у пользователя больше нет активных соединений —
            # откладываем объявление "вышел из чата": он мог просто
            # перезагрузить страницу или у него флапнула сеть.
            # Фоновое задание проверит переподключение через grace-период.
            if not user_still_online:
                await self.presence_mark_grace(user.username)
                await self.schedule_leave_check(user.username)

            # Обновляем список онлайн-пользователей.
            await self.broadcast_online_users()

        # Удаляем соединение из групп.
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name,
        )

        if hasattr(self, "user_group_name"):
            await self.channel_layer.group_discard(
                self.user_group_name,
                self.channel_name,
            )

    async def schedule_leave_check(self, username):
        """Запускает отложенную проверку "ухода" пользователя."""

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            return

        loop.create_task(self._delayed_leave(username))

    async def _delayed_leave(self, username):
        """Публикует "вышел из чата", если пользователь не вернулся."""

        await asyncio.sleep(RECONNECT_GRACE)

        grace_active = await self.presence_reconnect_grace(username)
        still_online = await self.presence_user_online(username)

        if grace_active and not still_online:
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "user_status",
                    "action": "leave",
                    "username": username,
                    "channel_name": None,
                },
            )

            await self.presence_clear_grace(username)

            await self.broadcast_online_users()

    async def user_status(self, event):
        """Отправляет системное событие о входе/выходе пользователя."""

        # Не отправляем событие обратно отправителю.
        if event.get("channel_name") and event["channel_name"] == self.channel_name:
            return

        await self.send(
            text_data=json.dumps(
                {
                    "type": "user_status",
                    "action": event["action"],
                    "username": event["username"],
                }
            )
        )

    async def receive(self, text_data):
        """Получает сообщение от клиента."""

        # Heartbeat-пинг: держим соединение живым через
        # прокси/балансировщики с idle-timeout (nginx и т.п.).
        try:
            incoming = json.loads(text_data)
        except json.JSONDecodeError:
            incoming = None

        if isinstance(incoming, dict) and incoming.get("type") == "ping":
            await self.send(
                text_data=json.dumps(
                    {
                        "type": "pong",
                    }
                )
            )
            return

        # Реакция (эмодзи) на сообщение.
        if isinstance(incoming, dict) and incoming.get("type") == "react":
            await self.handle_reaction(incoming)
            return

        # Комментарий к сообщению.
        if isinstance(incoming, dict) and incoming.get("type") == "comment":
            await self.handle_comment(incoming)
            return

        # Проверяем право отправлять сообщения.
        if not await self.can_send_messages(self.room):
            await self.send_ws_error(
                "Чтобы отправлять сообщения, нужно вступить в комнату."
            )
            return

        # Ограничиваем частоту отправки сообщений.
        if not await self.is_send_rate_ok():
            await self.send_ws_error(
                "Слишком много сообщений. Подождите немного."
            )
            return

        # Валидируем сообщение.
        message_text, error = validate_message(text_data)

        if error:
            await self.send_ws_error(error)
            return

        user = self.scope["user"]

        # Сохраняем сообщение в БД и сразу сериализуем его
        # (внутри sync-контекста, т.к. сериализация обращается к БД
        # за реакциями/комментариями).
        payload = await self.create_message_payload(
            user_id=user.id,
            room_id=self.room.id,
            text=message_text,
        )

        # Отправляем сообщение всем участникам комнаты.
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chat_message",
                **payload,
            },
        )

        # Сообщаем всем остальным участникам о непрочитанных.
        await self.notify_room_unread(user.id)

    async def handle_reaction(self, incoming):
        """Ставит или убирает реакцию (эмодзи) на сообщение."""

        if not await self.can_send_messages(self.room):
            await self.send_ws_error("Чтобы ставить реакции, нужно вступить в комнату.")
            return

        if not await self.is_send_rate_ok():
            await self.send_ws_error(
                "Слишком много сообщений. Подождите немного."
            )
            return

        try:
            message_id = int(incoming.get("message_id"))
        except (TypeError, ValueError):
            await self.send_ws_error("Неверный идентификатор сообщения.")
            return

        emoji = str(incoming.get("emoji") or "")[:8]

        if emoji not in REACTION_EMOJIS:
            await self.send_ws_error("Недопустимая реакция.")
            return

        user = self.scope["user"]

        # На свои сообщения реакции ставить нельзя.
        author_id = await self.get_message_author(
            self.room,
            message_id,
        )

        if author_id is None:
            await self.send_ws_error("Сообщение не найдено.")
            return

        if author_id == user.id:
            await self.send_ws_error("Нельзя ставить реакции на свои сообщения.")
            return

        # Переключаем реакцию: если пользователь уже поставил её —
        # убираем, иначе добавляем.
        await self.toggle_reaction(
            message_id=message_id,
            user_id=user.id,
            emoji=emoji,
        )

        reactions = await self.get_message_reactions(
            message_id=message_id,
        )

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "message_reaction",
                "message_id": message_id,
                "reactions": reactions,
            },
        )

    async def handle_comment(self, incoming):
        """Создаёт reply-сообщение с цитатой исходного текста."""

        if not await self.can_send_messages(self.room):
            await self.send_ws_error("Чтобы отвечать, нужно вступить в комнату.")
            return

        if not await self.is_send_rate_ok():
            await self.send_ws_error(
                "Слишком много сообщений. Подождите немного."
            )
            return

        try:
            reply_to_id = int(incoming.get("reply_to_id"))
        except (TypeError, ValueError):
            await self.send_ws_error("Неверный идентификатор сообщения.")
            return

        text = str(incoming.get("text") or "").strip()

        if not text:
            await self.send_ws_error("Ответ пуст.")
            return

        if len(text) > 1000:
            await self.send_ws_error("Ответ не должен превышать 1000 символов.")
            return

        user = self.scope["user"]

        # На свои сообщения отвечать (комментировать) нельзя.
        author_id = await self.get_message_author(
            self.room,
            reply_to_id,
        )

        if author_id is None:
            await self.send_ws_error("Сообщение не найдено.")
            return

        if author_id == user.id:
            await self.send_ws_error("Нельзя отвечать на свои сообщения.")
            return

        payload = await self.create_reply_message(
            reply_to_id=reply_to_id,
            user_id=user.id,
            room_id=self.room.id,
            text=text,
        )

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chat_message",
                **payload,
            },
        )

        await self.notify_room_unread(user.id)

    async def send_ws_error(self, message):
        await self.send(
            text_data=json.dumps(
                {
                    "type": "error",
                    "message": message,
                }
            )
        )

    async def message_reaction(self, event):
        """Рассылает обновлённый список реакций сообщения."""

        await self.send(
            text_data=json.dumps(
                {
                    "type": "reaction",
                    "message_id": event["message_id"],
                    "reactions": event["reactions"],
                }
            )
        )

    async def chat_message(self, event):
        """Отправляет сообщение клиенту."""

        await self.send(
            text_data=json.dumps(
                {
                    "type": "message",
                    "id": event.get("id"),
                    "username": event["username"],
                    "avatar": event.get("avatar"),
                    "message": event.get("message", ""),
                    "created_at": event.get("created_at"),
                    "edited_at": event.get("edited_at"),
                    "attachment": event.get("attachment"),
                    "attachment_type": (event.get("attachment_type", "")),
                    "attachment_name": (event.get("attachment_name", "")),
                    "reactions": event.get("reactions", []),
                    "reply_to": event.get("reply_to"),
                }
            )
        )

    async def message_updated(self, event):
        """Отправляет клиенту обновлённое содержимое сообщения."""

        await self.send(
            text_data=json.dumps(
                {
                    "type": "message_updated",
                    "message": event["message"],
                }
            )
        )

    async def message_deleted(self, event):
        """Отправляет клиенту сигнал об удалении сообщения."""

        await self.send(
            text_data=json.dumps(
                {
                    "type": "message_deleted",
                    "message_id": event["message_id"],
                }
            )
        )

    async def unread_update(self, event):
        """Отправляет клиенту актуальный счётчик непрочитанных сообщений."""

        await self.send(
            text_data=json.dumps(
                {
                    "type": "unread_update",
                    "room_id": event["room_id"],
                    "unread_count": event["unread_count"],
                }
            )
        )

    async def send_message_history(self):
        """Отправляет пользователю историю сообщений."""

        messages = await self.get_messages(
            self.room.id,
            self.scope["user"].id,
        )

        await self.send(
            text_data=json.dumps(
                {
                    "type": "history",
                    "messages": messages,
                }
            )
        )

    async def broadcast_online_users(self):
        """Рассылает участникам комнаты список онлайн-пользователей."""

        usernames = await self.presence_usernames()

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "online_users",
                "users": usernames,
            },
        )

    async def online_users(self, event):
        """Отправляет список онлайн-пользователей клиенту."""

        await self.send(
            text_data=json.dumps(
                {
                    "type": "online_users",
                    "users": event["users"],
                }
            )
        )

    # =========================
    # Database
    # =========================

    @database_sync_to_async
    def create_message_payload(
        self,
        user_id,
        room_id,
        text,
    ):
        """Создаёт сообщение в БД и сериализует его.

        Вся работа выполняется в sync-контексте: сериализация
        обращается к БД за реакциями/комментариями, а значит
        её нельзя вызывать из async-контекста (SynchronousOnlyOperation).
        """

        message = Message.objects.create(
            user_id=user_id,
            room_id=room_id,
            text=text,
        )

        message = Message.objects.select_related("user").get(pk=message.pk)

        return serialize_message(message)

    @database_sync_to_async
    def get_message_author(self, room, message_id):
        """Возвращает id автора сообщения в комнате
        (None, если сообщение не найдено).
        """

        return Message.objects.filter(id=message_id, room=room).values_list("user_id", flat=True).first()

    @database_sync_to_async
    def toggle_reaction(self, message_id, user_id, emoji):
        """Добавляет или убирает реакцию пользователя на сообщение."""

        reaction = MessageReaction.objects.filter(
            message_id=message_id,
            user_id=user_id,
            emoji=emoji,
        ).first()

        if reaction is not None:
            reaction.delete()
            return

        MessageReaction.objects.create(
            message_id=message_id,
            user_id=user_id,
            emoji=emoji,
        )

    @database_sync_to_async
    def get_message_reactions(self, message_id):
        """Возвращает агрегированные реакции сообщения для рассылки."""

        message = Message.objects.get(pk=message_id)

        return serialize_message(message)["reactions"]

    @database_sync_to_async
    def create_reply_message(self, reply_to_id, user_id, room_id, text):
        """Создаёт сообщение-ответ (reply) с цитатой исходного текста.

        Работает в sync-контексте — сериализация цитаты обращается
        к БД (SynchronousOnlyOperation).
        """

        message = Message.objects.create(
            user_id=user_id,
            room_id=room_id,
            text=text,
            reply_to_id=reply_to_id,
        )

        message = (
            Message.objects.select_related("user")
            .select_related("reply_to")
            .select_related("reply_to__user")
            .get(pk=message.pk)
        )

        return serialize_message(message)

    @database_sync_to_async
    def get_messages(self, room_id, current_user_id):
        """Возвращает последние сообщения комнаты (историю)."""

        messages = list(
            Message.objects.filter(room_id=room_id)
            .select_related("user")
            .select_related("reply_to__user")
            .order_by("-id")[:MESSAGE_HISTORY_LIMIT]
        )

        messages.reverse()

        return [
            serialize_message(
                message,
                current_user_id=current_user_id,
            )
            for message in messages
        ]

    async def notify_room_unread(self, sender_id):
        """Рассылвает участникам комнаты актуальные счётчики непрочитанных.

        Отправляется в личный канал каждого участника (кроме автора),
        чтобы клиент обновил бейджи в списке чатов в реальном времени.
        """

        member_ids = await self.room_member_ids(self.room.id)

        for user_id in member_ids:

            if user_id == sender_id:
                continue

            unread = await self.user_unread_count(
                self.room.id,
                user_id,
            )

            await self.channel_layer.group_send(
                f"user_{user_id}",
                {
                    "type": "unread_update",
                    "room_id": self.room.id,
                    "unread_count": unread,
                },
            )

    @database_sync_to_async
    def room_member_ids(self, room_id):
        return notifications.room_member_ids(room_id)

    @database_sync_to_async
    def user_unread_count(self, room_id, user_id):
        return notifications.user_unread_count(
            room_id,
            user_id,
        )

    @database_sync_to_async
    def get_room(self, room_name):
        """Получает комнату по имени."""

        try:
            return ChatRoom.objects.get(
                name=room_name,
            )
        except ChatRoom.DoesNotExist:
            return None

    @database_sync_to_async
    def has_room_access(self, room):
        """Проверяет доступ пользователя к комнате.

        Читать историю и сообщения могут только участники комнаты
        (владелец или участник). Это касается и публичных комнат:
        сначала нужно вступить в комнату.
        """

        return room.is_user_member(self.scope["user"])

    @database_sync_to_async
    def is_send_rate_ok(self):
        """Проверяет лимит частоты отправки сообщений для пользователя."""

        user = self.scope["user"]
        key_prefix = f"chat:send_rate:{user.id}:{self.room.id}"

        return rate_limit_allows(
            key_prefix=key_prefix,
            limit=SEND_RATE_LIMIT,
            window_seconds=SEND_RATE_WINDOW,
        )

    # =========================
    # Presence (кэш)
    # =========================

    @database_sync_to_async
    def presence_add(self, channel_name, username):
        return add_online_user(self.room_name, channel_name, username)

    @database_sync_to_async
    def presence_mark_grace(self, username):
        mark_reconnect_grace(self.room_name, username)

    @database_sync_to_async
    def presence_clear_grace(self, username):
        clear_reconnect_grace(self.room_name, username)

    @database_sync_to_async
    def presence_reconnect_grace(self, username):
        return is_reconnect_within_grace(
            self.room_name,
            username,
        )

    @database_sync_to_async
    def presence_user_online(self, username):
        return is_user_online(
            self.room_name,
            username,
        )

    @database_sync_to_async
    def presence_remove(self, channel_name, username):
        return remove_online_user(
            self.room_name,
            channel_name,
            username,
        )

    @database_sync_to_async
    def presence_usernames(self):
        return get_online_usernames(self.room_name)

    @database_sync_to_async
    def can_send_messages(self, room):
        """Проверяет право пользователя отправлять сообщения.

        Писать могут только участники комнаты (владелец тоже).
        """

        return room.is_user_member(self.scope["user"])
