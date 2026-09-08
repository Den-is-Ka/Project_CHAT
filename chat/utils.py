import os

from django.db.models import Count as _Count
from PIL import Image

# Защита от decompression bomb для изображений в сообщениях.
Image.MAX_IMAGE_PIXELS = 20_000_000


# Допустимые расширения файлов для вложений.
IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".bmp",
}

VIDEO_EXTENSIONS = {
    ".mp4",
    ".webm",
    ".ogv",
    ".mov",
    ".m4v",
}

AUDIO_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".ogg",
    ".oga",
    ".m4a",
    ".aac",
    ".opus",
    ".weba",
    ".flac",
}

FILE_EXTENSIONS = {
    ".pdf",
    ".txt",
    ".zip",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".pptx",
    ".csv",
    ".json",
    ".md",
    ".rtf",
    ".epub",
}

ALLOWED_EXTENSIONS = (
    IMAGE_EXTENSIONS
    | VIDEO_EXTENSIONS
    | AUDIO_EXTENSIONS
    | FILE_EXTENSIONS
)


from .models import REACTION_EMOJIS


def get_attachment_type(name, content_type=""):
    """Определяет тип вложенного файла по имени (и MIME)."""

    ext = os.path.splitext(name or "")[1].lower()

    if ext in IMAGE_EXTENSIONS:
        return "image"

    if ext in VIDEO_EXTENSIONS:
        return "video"

    if ext in AUDIO_EXTENSIONS:
        return "audio"

    if ext in FILE_EXTENSIONS:
        return "file"

    # Если расширение неизвестно — пробуем определить по MIME.
    if content_type:
        if content_type.startswith("image/"):
            return "image"

        if content_type.startswith("video/"):
            return "video"

        if content_type.startswith("audio/"):
            return "audio"

    return "file"


def validate_image_file(file):
    """Проверяет, что файл является корректным изображением.

    Возвращает True или бросает ValueError в случае проблемы.
    """

    try:
        image = Image.open(file)
        image.verify()
    except Exception as exc:
        raise ValueError(
            "Файл не является корректным изображением."
        ) from exc

    file.seek(0)

    return True


def serialize_message(message, current_user_id=None):
    """Сериализует сообщение для отправки по WebSocket / HTTP."""

    return {
        "id": message.id,
        "username": message.user.username,
        "avatar": (
            message.user.avatar.url
            if message.user.avatar
            else None
        ),
        "message": message.text,
        "created_at": message.created_at.isoformat(),
        "attachment": (
            message.attachment.url
            if message.attachment
            else None
        ),
        "attachment_type": message.attachment_type,
        "attachment_name": message.attachment_name,
        "reactions": _serialize_reactions(
            message,
            current_user_id,
        ),
        "reply_to": _serialize_reply_to(message),
    }


def _serialize_reply_to(message):
    """Сериализует исходное сообщение для цитаты reply.

    Возвращает данные исходного сообщения (или None), на которое
    ссылается данное сообщение.
    """

    reply_to = getattr(message, "_cached_reply_to", None)

    if hasattr(message, "_cached_reply_to_done"):
        reply_to = message._cached_reply_to
    else:
        original = message.reply_to

        if original is not None and not hasattr(
            original,
            "_cached_reply_snippet",
        ):
            original._cached_reply_snippet = {
                "id": original.id,
                "username": original.user.username,
                "avatar": (
                    original.user.avatar.url
                    if original.user.avatar
                    else None
                ),
                "message": original.text,
                "attachment": (
                    original.attachment.url
                    if original.attachment
                    else None
                ),
                "attachment_type": original.attachment_type,
                "attachment_name": original.attachment_name,
            }

        reply_to = (
            original._cached_reply_snippet
            if original is not None
            else None
        )

        message._cached_reply_to = reply_to
        message._cached_reply_to_done = True

    return reply_to


def _serialize_reactions(message, current_user_id=None):
    """Агрегирует реакции сообщения по эмодзи.

    Возвращает список вида [{"emoji", "count", "reacted_by_me"}].

    count — реальное количество реакций с данным эмодзи в БД.
    Поле reacted_by_me добавляется только когда известен
    current_user_id (история для конкретного пользователя);
    для равномерной live-рассылки его нет — клиент сам отслеживает
    собственные реакции.
    """

    if not hasattr(message, "_reaction_counts"):
        query = message.reactions.values("emoji").annotate(
            count=_Count("id")
        )
        message._reaction_counts = {
            item["emoji"]: item["count"]
            for item in query
        }

    has_current_user = current_user_id is not None

    if (
        has_current_user
        and not hasattr(message, "_my_reactions")
    ):
        message._my_reactions = set(
            message.reactions
            .filter(user_id=current_user_id)
            .values_list("emoji", flat=True)
        )

    my_reactions = getattr(
        message,
        "_my_reactions",
        set(),
    )

    result = []

    for emoji in REACTION_EMOJIS:
        count = message._reaction_counts.get(emoji, 0)
        by_me = emoji in my_reactions

        if count == 0 and not by_me:
            continue

        item = {
            "emoji": emoji,
            "count": count,
        }

        if has_current_user:
            item["reacted_by_me"] = by_me

        result.append(item)

    return result
