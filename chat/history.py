from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views import View

from .models import ChatRoom, Message
from .utils import serialize_message

HISTORY_PAGE_SIZE = 50


class MessageHistoryView(LoginRequiredMixin, View):
    """Возвращает страницу истории сообщений комнаты по id-курсору."""

    def get(self, request, room_id):
        room = get_object_or_404(
            ChatRoom,
            id=room_id,
        )

        if not room.is_user_member(request.user):
            raise PermissionDenied("У вас нет доступа к этой комнате.")

        before = request.GET.get("before")
        before_id = None

        if before not in (None, ""):
            try:
                before_id = int(before)
            except (TypeError, ValueError):
                return JsonResponse(
                    {
                        "success": False,
                        "error": "Параметр before должен быть положительным целым числом.",
                    },
                    status=400,
                )

            if before_id <= 0:
                return JsonResponse(
                    {
                        "success": False,
                        "error": "Параметр before должен быть положительным целым числом.",
                    },
                    status=400,
                )

        queryset = (
            Message.objects.filter(room=room)
            .select_related("user", "reply_to__user")
            .order_by("-id")
        )

        if before_id is not None:
            queryset = queryset.filter(id__lt=before_id)

        page = list(queryset[: HISTORY_PAGE_SIZE + 1])
        has_more = len(page) > HISTORY_PAGE_SIZE

        if has_more:
            page = page[:HISTORY_PAGE_SIZE]

        page.reverse()

        messages = [
            serialize_message(
                message,
                current_user_id=request.user.id,
            )
            for message in page
        ]

        next_before = None

        if has_more and messages:
            next_before = messages[0]["id"]

        return JsonResponse(
            {
                "messages": messages,
                "has_more": has_more,
                "next_before": next_before,
            }
        )
