from django.conf import settings
from django.db import models

# Префикс имён личных (1:1) комнат: "dm-<id_меньший>-<id_больший>".
DIRECT_MESSAGE_PREFIX = "dm-"


class Message(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chat_messages",
    )
    room = models.ForeignKey(
        "ChatRoom",
        on_delete=models.CASCADE,
        related_name="messages",
    )
    text = models.TextField(
        blank=True,
        default="",
    )
    attachment = models.FileField(
        upload_to="chat_files/",
        blank=True,
        null=True,
    )

    # Тип вложения: "image", "video", "audio" или "file".
    attachment_type = models.CharField(
        max_length=20,
        blank=True,
        default="",
    )
    attachment_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    # Сообщение, на которое дан ответ (цитата). Reply-сообщение
    # показывает исходное сообщение в рамке-цитате.
    reply_to = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        related_name="replies",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        if self.text:
            return f"{self.user.username}: {self.text}"

        if self.attachment_name:
            return f"{self.user.username}: {self.attachment_name}"

        return f"Сообщение #{self.pk}"


# Список эмодзи, которые можно ставить на сообщения как реакции.
REACTION_EMOJIS = (
    "👍",
    "❤️",
    "😂",
    "😮",
    "😢",
    "🔥",
    "👏",
    "🎉",
)


class MessageReaction(models.Model):
    """Реакция (эмодзи) пользователя на сообщение."""

    message = models.ForeignKey(
        "Message",
        on_delete=models.CASCADE,
        related_name="reactions",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="message_reactions",
    )
    emoji = models.CharField(max_length=8)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["message", "user", "emoji"],
                name="uniq_message_user_emoji",
            ),
        ]

    def __str__(self):
        return f"{self.user.username}: {self.emoji}"


class ChatRoom(models.Model):
    """Комната чата."""

    name = models.CharField(
        max_length=100,
        unique=True,
    )
    description = models.TextField(
        blank=True,
    )
    avatar = models.ImageField(
        upload_to="chat_rooms/",
        blank=True,
        null=True,
    )
    is_private = models.BooleanField(
        default=False,
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="owned_chat_rooms",
    )
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="chat_rooms",
        blank=True,
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    def __str__(self):
        return self.name

    @property
    def is_direct(self):
        return self.name.startswith(DIRECT_MESSAGE_PREFIX)

    def is_user_member(self, user):
        """Является ли пользователь участником комнаты (владелец сюда тоже входит)."""

        return (
            self.owner_id == user.id
            or self.members.filter(id=user.id).exists()
        )


class RoomReadState(models.Model):
    """Граница прочитанного: id последнего сообщения, которое видел пользователь.

    Непрочитанных в комнате = количество сообщений других пользователей
    с id больше last_read_message_id.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="room_read_states",
    )
    room = models.ForeignKey(
        "ChatRoom",
        on_delete=models.CASCADE,
        related_name="read_states",
    )
    last_read_message_id = models.BigIntegerField(
        default=0,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "room"],
                name="uniq_user_room_read_state",
            ),
        ]

    def __str__(self):
        return f"{self.user.username} @ {self.room.name}: " f"{self.last_read_message_id}"
