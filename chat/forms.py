from io import BytesIO

from django import forms
from django.core.files.base import ContentFile

from chat.models import ChatRoom
from chat.utils import (
    ALLOWED_EXTENSIONS,
    get_attachment_type,
    validate_image_file,
)
from users.models import User
from users.utils import resize_avatar

# Максимальный размер файла вложения (совпадает с nginx client_max_body_size).
MAX_ATTACHMENT_SIZE = 20 * 1024 * 1024


def _resize_room_avatar(avatar):
    """Подгоняет аватар комнаты под единый размер."""

    if not avatar:
        return avatar

    try:
        resized_image = resize_avatar(avatar)
    except Exception:
        raise forms.ValidationError("Не удалось обработать изображение.")

    buffer = BytesIO()

    resized_image.save(
        buffer,
        format="JPEG",
        quality=90,
    )

    return ContentFile(
        buffer.getvalue(),
        name="room_avatar.jpg",
    )


class ChatRoomForm(forms.ModelForm):
    """Форма создания комнаты."""

    class Meta:
        model = ChatRoom
        fields = (
            "name",
            "description",
            "avatar",
            "is_private",
        )
        labels = {
            "name": "Название комнаты",
            "description": "Описание",
            "avatar": "Аватар комнаты",
            "is_private": "Приватная комната",
        }
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "placeholder": "Введите название комнаты",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "placeholder": "Введите описание комнаты",
                    "rows": 4,
                }
            ),
            "avatar": forms.ClearableFileInput(),
        }

    def clean_avatar(self):
        return _resize_room_avatar(self.cleaned_data.get("avatar"))


class ChatRoomUpdateForm(forms.ModelForm):
    """Форма редактирования комнаты."""

    class Meta:
        model = ChatRoom
        fields = (
            "name",
            "description",
            "avatar",
            "is_private",
        )
        labels = {
            "name": "Название комнаты",
            "description": "Описание",
            "avatar": "Аватар комнаты",
            "is_private": "Приватная комната",
        }
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "placeholder": "Название комнаты",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "placeholder": "Описание комнаты",
                    "rows": 4,
                }
            ),
            "avatar": forms.ClearableFileInput(),
        }

    def clean_avatar(self):
        return _resize_room_avatar(self.cleaned_data.get("avatar"))


class AddRoomMemberForm(forms.Form):
    """Форма добавления пользователя в комнату."""

    user = forms.ModelChoiceField(
        queryset=User.objects.none(),
        label="Пользователь",
    )

    def __init__(self, *args, room=None, **kwargs):
        super().__init__(*args, **kwargs)

        if room is not None:
            self.fields["user"].queryset = (
                User.objects.exclude(id=room.owner_id)
                .exclude(id__in=room.members.values_list("id", flat=True))
                .order_by("username")
            )


class SendMediaMessageForm(forms.Form):
    """Форма отправки файла (фото, видео, аудио) в чат."""

    file = forms.FileField(
        label="Файл",
    )
    caption = forms.CharField(
        required=False,
        max_length=1000,
        label="Подпись",
    )
    reply_to_id = forms.IntegerField(
        required=False,
        min_value=1,
        label="Сообщение, на которое дан ответ",
    )

    def clean_file(self):
        file = self.cleaned_data.get("file")

        if file is None:
            raise forms.ValidationError("Файл не выбран.")

        if file.size > MAX_ATTACHMENT_SIZE:
            raise forms.ValidationError("Файл не должен превышать 20 МБ.")

        ext = (file.name or "").lower()

        if get_attachment_type(ext, file.content_type) == "file" and not ext.endswith(tuple(ALLOWED_EXTENSIONS)):
            raise forms.ValidationError("Недопустимый тип файла.")

        if get_attachment_type(ext, file.content_type) == "image":
            try:
                validate_image_file(file)
            except ValueError as exc:
                raise forms.ValidationError(str(exc)) from exc

        file.seek(0)

        return file

    def clean_caption(self):
        caption = self.cleaned_data.get("caption") or ""

        return caption.strip()
