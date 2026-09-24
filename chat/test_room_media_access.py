from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import ChatRoom, Message

User = get_user_model()


class RoomMediaAccessTests(TestCase):
    """Медиа публичной комнаты не раскрываются пользователям вне комнаты."""

    def setUp(self):
        self.owner = User.objects.create_user(
            username="media-owner",
            password="pass-media-owner-123",
        )
        self.member = User.objects.create_user(
            username="media-member",
            password="pass-media-member-123",
        )
        self.outsider = User.objects.create_user(
            username="media-outsider",
            password="pass-media-outsider-123",
        )

        self.room = ChatRoom.objects.create(
            name="media-public-room",
            owner=self.owner,
            is_private=False,
        )
        self.room.members.add(self.owner, self.member)

        self.message = Message.objects.create(
            user=self.owner,
            room=self.room,
            text="секретная ссылка https://example.com/room-only",
        )

        self.url = reverse(
            "room_media",
            kwargs={"room_id": self.room.id},
        )

    def test_non_member_cannot_read_public_room_media(self):
        self.client.force_login(self.outsider)

        response = self.client.get(
            self.url,
            HTTP_HOST="testserver",
        )

        self.assertEqual(response.status_code, 403)

    def test_member_can_read_public_room_media(self):
        self.client.force_login(self.member)

        response = self.client.get(
            self.url,
            HTTP_HOST="testserver",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["links"]), 1)
        self.assertEqual(
            payload["links"][0]["id"],
            self.message.id,
        )
