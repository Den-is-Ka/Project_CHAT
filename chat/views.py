import re
import time

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, models
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from chat.forms import (
    AddRoomMemberForm,
    ChatRoomForm,
    ChatRoomUpdateForm,
    SendMediaMessageForm,
)
from chat.models import (
    DIRECT_MESSAGE_PREFIX,
    ChatRoom,
    Message,
    RoomReadState,
)
from chat.notifications import notify_room_unread, user_unread_count
from chat.utils import get_attachment_type, serialize_message
from users.models import User

# Ограничение загрузки файлов: не более MAX_MEDIA_UPLOADS за окно в секунду.
MAX_MEDIA_UPLOADS = 30
MEDIA_UPLOAD_WINDOW = 60

# Регулярное выражение для поиска ссылок в тексте сообщения.
_URL_RE = re.compile(
    r"(?:https?://|www\.)\S+",
    re.IGNORECASE,
)

# Максимальное число сообщений, просматриваемых при сборе медиа.
MEDIA_LIMIT = 500


def _first_url(text):
    """Возвращает первую найденную в тексте ссылку (или None)."""

    match = _URL_RE.search(text or "")

    if not match:
        return None

    url = match.group(0).rstrip(".,;:!?…)]}\"'")

    if url.startswith("www."):
        url = "https://" + url

    return url


def _serialize_media_item(message):
    """Лёгкая сериализация сообщения для панели «Медиа»."""

    return {
        "id": message.id,
        "username": message.user.username,
        "avatar": (message.user.avatar.url if message.user.avatar else None),
        "text": message.text,
        "created_at": message.created_at.isoformat(),
        "attachment": (message.attachment.url if message.attachment else None),
        "attachment_type": message.attachment_type,
        "attachment_name": message.attachment_name,
    }


def _available_rooms(user):
    """Комнаты, доступные пользователю."""

    if user.is_authenticated:
        return ChatRoom.objects.filter(
            models.Q(is_private=False) | models.Q(members=user) | models.Q(owner=user)
        ).distinct()

    return ChatRoom.objects.filter(is_private=False)


def _room_display_name(room, current_user):
    """Отображаемое имя комнаты.

    Для личных (DM) комнат показывает собеседника,
    а не внутреннее имя вида "dm-1-2".
    """

    if room.is_direct and current_user.is_authenticated:
        other = room.members.exclude(id=current_user.id).first()

        if other is not None:
            return other.username

    return room.name


def _mark_room_read(user, room):
    """Фиксирует, что пользователь прочитал все сообщения комнаты."""

    last_message_id = Message.objects.filter(room=room).order_by("-id").values_list("id", flat=True).first() or 0

    RoomReadState.objects.update_or_create(
        user=user,
        room=room,
        defaults={
            "last_read_message_id": last_message_id,
        },
    )


def _rooms_with_unread(user, rooms_queryset):
    """Возвращает список комнат с полем unread_count.

    Комнаты с непрочитанными сообщениями идут первыми.
    Порядок остальных сохраняется (стабильная сортировка).
    """

    rooms = list(rooms_queryset)

    for room in rooms:
        room.display_name = _room_display_name(
            room,
            user if user.is_authenticated else None,
        )

    if not user.is_authenticated:
        for room in rooms:
            room.unread_count = 0

        return rooms

    room_ids = [room.id for room in rooms]

    read_states = {
        state.room_id: state.last_read_message_id
        for state in RoomReadState.objects.filter(
            user=user,
            room_id__in=room_ids,
        )
    }

    for room in rooms:
        last_read_id = read_states.get(room.id, 0)

        if not room.is_user_member(user):
            room.unread_count = 0
            continue

        room.unread_count = user_unread_count(
            room.id,
            user.id,
            last_read_id,
        )

    rooms.sort(key=lambda room: -room.unread_count)

    return rooms


def first_chat(request):
    """Перенаправляет пользователя в первую доступную комнату.

    Заменяет жёстко зашитые ссылки на комнату "general",
    которая может не существовать.
    """

    room = _available_rooms(request.user).order_by("id").first()

    if room is None:
        return redirect(reverse("home"))

    return redirect(
        reverse(
            "chat",
            kwargs={"room_name": room.name},
        )
    )


def chat_page(request, room_name):
    room = get_object_or_404(
        ChatRoom.objects.prefetch_related("members"),
        name=room_name,
    )

    room.display_name = _room_display_name(
        room,
        request.user if request.user.is_authenticated else None,
    )

    is_room_member = False

    if request.user.is_authenticated:
        is_room_member = room.is_user_member(request.user)

        if room.is_private and not is_room_member:
            raise PermissionDenied("У вас нет доступа к этой комнате.")

        if is_room_member:
            _mark_room_read(request.user, room)

    available_users = User.objects.none()

    if request.user.is_authenticated and room.owner_id == request.user.id:
        available_users = (
            AddRoomMemberForm(
                room=room,
            )
            .fields["user"]
            .queryset
        )

    rooms = _rooms_with_unread(
        request.user,
        _available_rooms(request.user),
    )

    # Личные (dm-*) комнаты — это "контакты", остальные — "чаты".
    contacts = sorted(
        (r for r in rooms if r.is_direct),
        key=lambda r: r.display_name.lower(),
    )
    chat_rooms = [r for r in rooms if not r.is_direct]

    return render(
        request,
        "chat/chat.html",
        {
            "room": room,
            "room_name": room.name,
            "is_direct": room.is_direct,
            "rooms": chat_rooms,
            "contacts": contacts,
            "room_members": room.members.all(),
            "is_room_owner": (request.user.is_authenticated and room.owner_id == request.user.id),
            "is_room_member": is_room_member,
            "available_users": available_users,
        },
    )


def _room_payload(room):
    """Данные комнаты для ответа клиенту."""

    return {
        "id": room.id,
        "name": room.name,
        "description": room.description,
        "avatar": (room.avatar.url if room.avatar else None),
        "is_private": room.is_private,
    }


def _duplicate_name_response():
    """Ответ при попытке создать/переименовать в занятое имя."""

    return JsonResponse(
        {
            "success": False,
            "errors": {
                "name": [
                    {
                        "message": ("Комната с таким названием " "уже существует."),
                    }
                ]
            },
        },
        status=400,
    )


def _dm_room_name(user_id_a, user_id_b):
    """Создаёт детерминированное имя приватной 1:1 комнаты.

    Не зависит от порядка аргументов: оба пользователя всегда
    получают одно и то же имя для одной и той же пары.
    """

    low, high = sorted((user_id_a, user_id_b))

    return f"{DIRECT_MESSAGE_PREFIX}{low}-{high}"


class CreateRoomView(LoginRequiredMixin, View):
    """Создание комнаты."""

    def post(self, request):
        form = ChatRoomForm(
            request.POST,
            request.FILES,
        )

        if not form.is_valid():
            return JsonResponse(
                {
                    "success": False,
                    "errors": form.errors,
                },
                status=400,
            )

        room = form.save(commit=False)
        room.owner = request.user

        try:
            room.save()
        except IntegrityError:
            return _duplicate_name_response()

        room.members.add(request.user)

        return JsonResponse(
            {
                "success": True,
                "room": _room_payload(room),
            },
            status=201,
        )


class UpdateRoomView(LoginRequiredMixin, View):
    """Редактирование комнаты."""

    def post(self, request, room_id):
        room = get_object_or_404(
            ChatRoom,
            id=room_id,
        )

        if room.owner_id != request.user.id:
            raise PermissionDenied("Только владелец комнаты может " "изменять её настройки.")

        form = ChatRoomUpdateForm(
            request.POST,
            request.FILES,
            instance=room,
        )

        if not form.is_valid():
            return JsonResponse(
                {
                    "success": False,
                    "errors": form.errors,
                },
                status=400,
            )

        try:
            room = form.save()
        except IntegrityError:
            return _duplicate_name_response()

        return JsonResponse(
            {
                "success": True,
                "room": _room_payload(room),
            }
        )


class AddRoomMemberView(LoginRequiredMixin, View):
    """Добавление участника в комнату."""

    def post(self, request, room_id):
        room = get_object_or_404(
            ChatRoom,
            id=room_id,
        )

        if room.owner_id != request.user.id:
            raise PermissionDenied("Только владелец комнаты может " "добавлять участников.")

        form = AddRoomMemberForm(
            request.POST,
            room=room,
        )

        if not form.is_valid():
            return JsonResponse(
                {
                    "success": False,
                    "errors": form.errors,
                },
                status=400,
            )

        user = form.cleaned_data["user"]

        room.members.add(user)

        return JsonResponse(
            {
                "success": True,
                "member": {
                    "id": user.id,
                    "username": user.username,
                    "avatar": (user.avatar.url if user.avatar else None),
                },
            },
            status=201,
        )


class RemoveRoomMemberView(LoginRequiredMixin, View):
    """Удаление участника владельцем комнаты."""

    def post(self, request, room_id, user_id):
        room = get_object_or_404(
            ChatRoom,
            id=room_id,
        )

        if room.owner_id != request.user.id:
            raise PermissionDenied("Только владелец комнаты может " "удалять участников.")

        if user_id == room.owner_id:
            return JsonResponse(
                {
                    "success": False,
                    "error": ("Владелец комнаты не может " "быть удалён."),
                },
                status=400,
            )

        user = get_object_or_404(
            User,
            id=user_id,
        )

        room.members.remove(user)

        return JsonResponse(
            {
                "success": True,
                "user_id": user.id,
            }
        )


class LeaveRoomView(LoginRequiredMixin, View):
    """Выход текущего пользователя из комнаты."""

    def post(self, request, room_id):
        room = get_object_or_404(
            ChatRoom,
            id=room_id,
        )

        if room.owner_id == request.user.id:
            return JsonResponse(
                {
                    "success": False,
                    "error": ("Владелец комнаты не может " "покинуть её."),
                },
                status=400,
            )

        room.members.remove(request.user)

        available_room = (
            _available_rooms(request.user)
            .exclude(id=room.id)
            .order_by("id")
            .first()
        )

        if available_room:
            redirect_url = reverse(
                "chat",
                kwargs={
                    "room_name": available_room.name,
                },
            )
        else:
            redirect_url = "/"

        return JsonResponse(
            {
                "success": True,
                "redirect_url": redirect_url,
            }
        )


class JoinRoomView(LoginRequiredMixin, View):
    """Вступление пользователя в публичную комнату."""

    def post(self, request, room_id):
        room = get_object_or_404(
            ChatRoom,
            id=room_id,
        )

        if room.is_private:
            return JsonResponse(
                {
                    "success": False,
                    "error": "В приватную комнату можно попасть только по приглашению.",
                },
                status=403,
            )

        if room.owner_id == request.user.id:
            return JsonResponse(
                {
                    "success": True,
                }
            )

        room.members.add(request.user)

        return JsonResponse(
            {
                "success": True,
                "room": {
                    "id": room.id,
                    "name": room.name,
                },
            }
        )


class SendMediaMessageView(LoginRequiredMixin, View):
    """Отправка файла (фото, видео, аудио) в комнату."""

    def post(self, request, room_id):
        room = get_object_or_404(
            ChatRoom,
            id=room_id,
        )

        if not room.is_user_member(request.user):
            raise PermissionDenied("У вас нет доступа к этой комнате.")

        if not self.is_upload_rate_ok(request, room):
            return JsonResponse(
                {
                    "success": False,
                    "error": ("Слишком много файлов. " "Подождите немного."),
                },
                status=429,
            )

        form = SendMediaMessageForm(
            request.POST,
            request.FILES,
        )

        if not form.is_valid():
            return JsonResponse(
                {
                    "success": False,
                    "errors": form.errors,
                },
                status=400,
            )

        file = form.cleaned_data["file"]
        caption = form.cleaned_data["caption"]
        reply_to_id = form.cleaned_data.get("reply_to_id")

        reply_to = None

        if reply_to_id:
            reply_to = Message.objects.filter(
                id=reply_to_id,
                room=room,
            ).first()

            if reply_to is None:
                return JsonResponse(
                    {
                        "success": False,
                        "error": "Сообщение не найдено.",
                    },
                    status=400,
                )

            if reply_to.user_id == request.user.id:
                return JsonResponse(
                    {
                        "success": False,
                        "error": "Нельзя отвечать на свои сообщения.",
                    },
                    status=400,
                )

        message = Message.objects.create(
            user=request.user,
            room=room,
            text=caption,
            attachment=file,
            attachment_type=get_attachment_type(
                file.name,
                file.content_type,
            ),
            attachment_name=file.name,
            reply_to=reply_to,
        )

        payload = serialize_message(
            message,
            current_user_id=request.user.id,
        )

        channel_layer = get_channel_layer()

        if channel_layer is not None:
            async_to_sync(channel_layer.group_send)(
                f"chat_{room.id}",
                {
                    "type": "chat_message",
                    **payload,
                },
            )

        notify_room_unread(room.id, request.user.id)

        return JsonResponse(
            {
                "success": True,
                "message": payload,
            },
            status=201,
        )

    def is_upload_rate_ok(self, request, room):
        """Ограничивает частоту загрузки файлов через кэш."""

        window = int(time.time()) // MEDIA_UPLOAD_WINDOW
        key = f"chat:media_rate:" f"{request.user.id}:{room.id}:{window}"

        count = cache.get(key, 0)

        if count >= MAX_MEDIA_UPLOADS:
            return False

        cache.set(
            key,
            count + 1,
            MEDIA_UPLOAD_WINDOW + 10,
        )

        return True


class RoomMediaView(LoginRequiredMixin, View):
    """Список медиа комнаты по группам: фото, видео, документы, ссылки."""

    def get(self, request, room_id):
        room = get_object_or_404(
            ChatRoom,
            id=room_id,
        )

        if room.is_private and not room.is_user_member(
            request.user,
        ):
            raise PermissionDenied("У вас нет доступа к этой комнате.")

        messages = room.messages.select_related("user").order_by("-created_at")[:MEDIA_LIMIT]

        photos = []
        videos = []
        documents = []
        links = []

        for message in messages:
            if message.attachment:
                item = _serialize_media_item(message)

                if message.attachment_type == "image":
                    photos.append(item)
                elif message.attachment_type == "video":
                    videos.append(item)
                else:
                    documents.append(item)

                continue

            url = _first_url(message.text)

            if url:
                item = _serialize_media_item(message)
                item["link"] = url
                links.append(item)

        return JsonResponse(
            {
                "photos": photos,
                "videos": videos,
                "documents": documents,
                "links": links,
            }
        )


class DirectMessageView(LoginRequiredMixin, View):
    """Открывает (или создаёт) личный чат с другим пользователем."""

    def post(self, request):
        username = (request.POST.get("username") or "").strip()

        if not username:
            return JsonResponse(
                {
                    "success": False,
                    "message": ("Не указан получатель сообщения."),
                },
                status=400,
            )

        target = User.objects.filter(username=username).first()

        if target is None:
            return JsonResponse(
                {
                    "success": False,
                    "message": ("Пользователь не найден."),
                },
                status=404,
            )

        if target.id == request.user.id:
            return JsonResponse(
                {
                    "success": False,
                    "message": ("Нельзя написать самому себе."),
                },
                status=400,
            )

        room_name = _dm_room_name(
            request.user.id,
            target.id,
        )

        room = ChatRoom.objects.filter(name=room_name).first()

        if room is None:
            try:
                room = ChatRoom.objects.create(
                    name=room_name,
                    owner=request.user,
                    is_private=True,
                )
            except IntegrityError:
                # Кто-то успел создать комнату раньше —
                # перечитываем.
                room = ChatRoom.objects.filter(name=room_name).first()

        if room is None:
            return JsonResponse(
                {
                    "success": False,
                    "message": ("Не удалось создать чат. Попробуйте ещё раз."),
                },
                status=500,
            )

        # Оба пользователя — участники личного чата.
        room.members.add(request.user)
        room.members.add(target)

        return JsonResponse(
            {
                "success": True,
                "url": reverse(
                    "chat",
                    kwargs={"room_name": room.name},
                ),
            }
        )


class MarkRoomReadView(LoginRequiredMixin, View):
    """Помечает комнату прочитанной (вызывается из чата)."""

    def post(self, request, room_id):
        room = get_object_or_404(
            ChatRoom,
            id=room_id,
        )

        if not room.is_user_member(request.user):
            raise PermissionDenied("У вас нет доступа к этой комнате.")

        _mark_room_read(
            request.user,
            room,
        )

        return JsonResponse({"success": True})


def _broadcast(room, payload):
    """Отправляет событие всем подключённым клиентам комнаты."""

    channel_layer = get_channel_layer()

    if channel_layer is None:
        return

    async_to_sync(channel_layer.group_send)(
        f"chat_{room.id}",
        payload,
    )


class MessageEditView(LoginRequiredMixin, View):
    """Изменение текста сообщения (только автором)."""

    def post(self, request, message_id):
        message = get_object_or_404(
            Message.objects.select_related("room", "user"),
            id=message_id,
        )

        if message.user_id != request.user.id:
            raise PermissionDenied("Редактировать сообщение может только его автор.")

        text = (request.POST.get("text") or "").strip()

        if not text:
            return JsonResponse(
                {
                    "success": False,
                    "error": "Сообщение не может быть пустым.",
                },
                status=400,
            )

        if len(text) > 1000:
            return JsonResponse(
                {
                    "success": False,
                    "error": "Сообщение не может быть длиннее 1000 символов.",
                },
                status=400,
            )

        message.text = text
        message.edited_at = timezone.now()
        message.save(update_fields=["text", "edited_at"])

        payload = serialize_message(message)

        _broadcast(
            message.room,
            {
                "type": "message_updated",
                "message": payload,
            },
        )

        return JsonResponse(
            {
                "success": True,
                "message": payload,
            }
        )


class MessageDeleteView(LoginRequiredMixin, View):
    """Удаление сообщения (автором или владельцем комнаты)."""

    def post(self, request, message_id):
        message = get_object_or_404(
            Message.objects.select_related("room"),
            id=message_id,
        )

        if (
            message.user_id != request.user.id
            and message.room.owner_id != request.user.id
        ):
            raise PermissionDenied(
                "Удалять сообщение может только его автор или владелец комнаты."
            )

        room = message.room

        message.delete()

        _broadcast(
            room,
            {
                "type": "message_deleted",
                "message_id": message_id,
            },
        )

        # После удаления счётчики непрочитанных могли измениться.
        notify_room_unread(room.id, request.user.id)

        return JsonResponse({"success": True})


class MessageForwardView(LoginRequiredMixin, View):
    """Пересылает сообщение в выбранную комнату."""

    def post(self, request, message_id):
        source_message = get_object_or_404(
            Message.objects.select_related("room"),
            id=message_id,
        )

        raw_target_room_id = request.POST.get("target_room_id")

        try:
            target_room_id = int(raw_target_room_id)
        except (TypeError, ValueError):
            return JsonResponse(
                {
                    "success": False,
                    "error": "Выберите комнату.",
                },
                status=400,
            )

        target_room = get_object_or_404(
            ChatRoom,
            id=target_room_id,
        )

        if not target_room.is_user_member(request.user):
            raise PermissionDenied("У вас нет доступа к этой комнате.")

        message = Message.objects.create(
            user=request.user,
            room=target_room,
            text=source_message.text,
            attachment=source_message.attachment,
            attachment_type=source_message.attachment_type,
            attachment_name=source_message.attachment_name,
        )

        message = (
            Message.objects.select_related("user")
            .get(pk=message.pk)
        )

        payload = serialize_message(message)

        _broadcast(
            target_room,
            {
                "type": "chat_message",
                **payload,
            },
        )

        notify_room_unread(target_room.id, request.user.id)

        return JsonResponse(
            {
                "success": True,
                "message": payload,
            }
        )
