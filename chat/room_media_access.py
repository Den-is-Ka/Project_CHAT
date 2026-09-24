from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from .models import ChatRoom
from .views import RoomMediaView


class MemberRoomMediaView(RoomMediaView):
    """Показывает медиа комнаты только её участникам."""

    def get(self, request, room_id):
        room = get_object_or_404(
            ChatRoom,
            id=room_id,
        )

        if not room.is_user_member(request.user):
            raise PermissionDenied("У вас нет доступа к этой комнате.")

        return super().get(request, room_id)
