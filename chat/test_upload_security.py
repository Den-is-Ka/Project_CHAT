from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase

from .models import ChatRoom, Message

User = get_user_model()


class SendMediaMessageSecurityTests(TransactionTestCase):
    """Проверки безопасности загрузки вложений."""

    def setUp(self):
        self.member = User.objects.create_user(
            username="upload-member",
            password="pass-member-123",
        )
        self.room = ChatRoom.objects.create(
            name="upload-security-room",
            owner=self.member,
        )
        self.room.members.add(self.member)

    def test_disallowed_extension_cannot_bypass_with_video_mime(self):
        self.client.force_login(self.member)

        invalid = SimpleUploadedFile(
            "payload.exe",
            b"not a real video",
            content_type="video/mp4",
        )

        response = self.client.post(
            f"/chat/rooms/{self.room.id}/send_file/",
            {"file": invalid},
            HTTP_HOST="testserver",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            Message.objects.filter(room=self.room).exists()
        )
