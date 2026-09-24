from django.contrib.auth import get_user_model
from django.test import TestCase

from .history import HISTORY_PAGE_SIZE
from .models import ChatRoom, Message

User = get_user_model()


class MessageHistoryPaginationTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="history-owner",
            password="pass-owner-123",
        )
        self.member = User.objects.create_user(
            username="history-member",
            password="pass-member-123",
        )
        self.other = User.objects.create_user(
            username="history-other",
            password="pass-other-123",
        )
        self.room = ChatRoom.objects.create(
            name="history-room",
            owner=self.owner,
        )
        self.room.members.add(self.member)
        self.messages = [
            Message.objects.create(
                user=self.owner,
                room=self.room,
                text=f"message-{index}",
            )
            for index in range(HISTORY_PAGE_SIZE + 5)
        ]
        self.url = f"/chat/rooms/{self.room.id}/history/"

    def test_requires_authentication(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_non_member_cannot_read_public_room_history(self):
        self.client.force_login(self.other)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_owner_can_read_history_without_explicit_membership(self):
        self.client.force_login(self.owner)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

    def test_first_page_returns_latest_messages_in_chronological_order(self):
        self.client.force_login(self.member)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)

        payload = response.json()
        ids = [message["id"] for message in payload["messages"]]
        expected = [message.id for message in self.messages[-HISTORY_PAGE_SIZE:]]

        self.assertEqual(ids, expected)
        self.assertTrue(payload["has_more"])
        self.assertEqual(payload["next_before"], expected[0])

    def test_before_cursor_returns_older_messages(self):
        self.client.force_login(self.member)
        cursor = self.messages[-HISTORY_PAGE_SIZE].id

        response = self.client.get(
            self.url,
            {"before": cursor},
        )

        self.assertEqual(response.status_code, 200)

        payload = response.json()
        ids = [message["id"] for message in payload["messages"]]
        expected = [message.id for message in self.messages[:5]]

        self.assertEqual(ids, expected)
        self.assertFalse(payload["has_more"])
        self.assertIsNone(payload["next_before"])

    def test_invalid_before_cursor_returns_400(self):
        self.client.force_login(self.member)

        for value in ("abc", "0", "-1"):
            with self.subTest(value=value):
                response = self.client.get(
                    self.url,
                    {"before": value},
                )

                self.assertEqual(response.status_code, 400)
