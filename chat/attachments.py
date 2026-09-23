import mimetypes
from pathlib import PurePosixPath
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse
from django.views import View

from .models import Message

CHAT_ATTACHMENT_PREFIX = "chat_files/"


def _attachment_storage_name(attachment_path):
    """Возвращает безопасное имя файла внутри chat_files/."""

    if not attachment_path:
        raise Http404

    path = PurePosixPath(attachment_path)

    if path.is_absolute() or ".." in path.parts:
        raise Http404

    normalized = str(path)

    if normalized in {"", "."}:
        raise Http404

    return f"{CHAT_ATTACHMENT_PREFIX}{normalized}"


class ProtectedChatAttachmentView(LoginRequiredMixin, View):
    """Отдаёт вложение только участнику комнаты сообщения."""

    def get(self, request, attachment_path):
        storage_name = _attachment_storage_name(attachment_path)

        messages = Message.objects.filter(
            attachment=storage_name,
        )

        if not messages.exists():
            raise Http404

        message = (
            messages.filter(
                Q(room__owner=request.user)
                | Q(room__members=request.user)
            )
            .distinct()
            .first()
        )

        if message is None:
            raise PermissionDenied(
                "У вас нет доступа к этому вложению."
            )

        content_type = (
            mimetypes.guess_type(
                message.attachment_name or storage_name
            )[0]
            or "application/octet-stream"
        )

        if settings.USE_NGINX_PROTECTED_MEDIA:
            response = HttpResponse(
                content_type=content_type,
            )
            response["X-Accel-Redirect"] = (
                "/_protected_chat_files/"
                + quote(attachment_path, safe="/")
            )
            response["X-Content-Type-Options"] = "nosniff"
            return response

        try:
            file_handle = message.attachment.open("rb")
        except FileNotFoundError as exc:
            raise Http404 from exc

        response = FileResponse(
            file_handle,
            content_type=content_type,
        )
        response["X-Content-Type-Options"] = "nosniff"
        return response
