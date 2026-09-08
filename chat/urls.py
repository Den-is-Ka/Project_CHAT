from django.urls import path

from .views import (
    AddRoomMemberView,
    CreateRoomView,
    JoinRoomView,
    LeaveRoomView,
    RemoveRoomMemberView,
    RoomMediaView,
    SendMediaMessageView,
    UpdateRoomView,
    chat_page,
    first_chat,
)


urlpatterns = [
    path(
        "start/",
        first_chat,
        name="first_chat",
    ),

    path(
        "rooms/create/",
        CreateRoomView.as_view(),
        name="create_room",
    ),

    path(
        "rooms/<int:room_id>/join/",
        JoinRoomView.as_view(),
        name="join_room",
    ),

    path(
        "rooms/<int:room_id>/update/",
        UpdateRoomView.as_view(),
        name="update_room",
    ),

    path(
        "rooms/<int:room_id>/members/",
        AddRoomMemberView.as_view(),
        name="add_room_member",
    ),

    path(
        "rooms/<int:room_id>/members/<int:user_id>/remove/",
        RemoveRoomMemberView.as_view(),
        name="remove_room_member",
    ),

    path(
        "rooms/<int:room_id>/leave/",
        LeaveRoomView.as_view(),
        name="leave_room",
    ),

    path(
        "rooms/<int:room_id>/send_file/",
        SendMediaMessageView.as_view(),
        name="send_message_file",
    ),

    path(
        "rooms/<int:room_id>/media/",
        RoomMediaView.as_view(),
        name="room_media",
    ),

    path(
        "<str:room_name>/",
        chat_page,
        name="chat",
    ),
]