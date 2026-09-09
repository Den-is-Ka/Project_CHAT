"""Рассылка событий о непрочитанных сообщениях.

Каждому участнику комнаты отправляется актуальный счётчик
непрочитанных сообщений в его личный канал (user_<id>),
чтобы бейджи в списке чатов обновлялись в реальном времени,
а не после перезагрузки страницы.
"""

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .models import ChatRoom, Message, RoomReadState


def room_member_ids(room_id):
    """Id всех участников комнаты, включая владельца."""

    room = ChatRoom.objects.get(pk=room_id)

    ids = set(room.members.values_list("id", flat=True))
    ids.add(room.owner_id)

    return ids


def user_unread_count(room_id, user_id, last_read_id=None):
    """Количество непрочитанных сообщений пользователя в комнате.

    Если last_read_id не передан, граница прочитанного берётся
    из RoomReadState (или 0, если записи нет).
    """

    if last_read_id is None:
        state = (
            RoomReadState.objects.filter(
                user_id=user_id,
                room_id=room_id,
            ).first()
        )

        last_read_id = (
            state.last_read_message_id
            if state is not None
            else 0
        )

    return (
        Message.objects.filter(
            room_id=room_id,
            id__gt=last_read_id,
        )
        .exclude(user_id=user_id)
        .count()
    )


def notify_room_unread(room_id, sender_id):
    """Отправляет счётчики непрочитанных всем участникам комнаты.

    Автор сообщения счётчик не получает: свои сообщения не
    учитываются в непрочитанных.
    """

    channel_layer = get_channel_layer()

    if channel_layer is None:
        return

    for user_id in room_member_ids(room_id):

        if user_id == sender_id:
            continue

        async_to_sync(channel_layer.group_send)(
            f"user_{user_id}",
            {
                "type": "unread_update",
                "room_id": room_id,
                "unread_count": user_unread_count(
                    room_id,
                    user_id,
                ),
            },
        )