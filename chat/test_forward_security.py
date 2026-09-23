from django.contrib.auth import get_user_model
from django.test import TransactionTestCase

from .models import ChatRoom, Message

User = get_user_model()


class MessageForwardSecurityTests(TransactionTestCase):
    """Пересылка не должна раскрывать сообщения из чужих комнат."""

    def setUp(self):
        self.victim = User.objects.create_user(
            username="forward-victim",
            password="pass-forward-victim-123",
        )
        self.attacker = User.objects.create_user(
            username="forward-attacker",
            password="pass-forward-attacker-123",
        )

        self.private_room = ChatRoom.objects.create(
            name="forward-private-source",
            owner=self.victim,
            is_private=True,
        )
        self.private_room.members.add(self.victim)

        self.target_room = ChatRoom.objects.create(
            name="forward-attacker-target",
            owner=self.attacker,
        )
        self.target_room.members.add(self.attacker)

        self.secret_message = Message.objects.create(
            user=self.victim,
            room=self.private_room,
            text="секретное сообщение",
        )

    def test_non_member_cannot_forward_message_from_private_room(self):
        self.client.force_login(self.attacker)

        response = self.client.post(
            f"/chat/messages/{self.secret_message.id}/forward/",
            {"target_room_id": self.target_room.id},
            HTTP_HOST="testserver",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            Message.objects.filter(
                room=self.target_room,
                user=self.attacker,
            ).exists()
        )
