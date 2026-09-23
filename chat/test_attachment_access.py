from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from .models import ChatRoom, Message

User = get_user_model()


class ProtectedChatAttachmentTests(TestCase):
    """Вложения сообщений доступны только участникам их комнат."""

    def setUp(self):
        self.media_dir = TemporaryDirectory()
        self.addCleanup(self.media_dir.cleanup)

        self.media_settings = override_settings(
            MEDIA_ROOT=self.media_dir.name,
            USE_NGINX_PROTECTED_MEDIA=False,
        )
        self.media_settings.enable()
        self.addCleanup(self.media_settings.disable)

        self.owner = User.objects.create_user(
            username="attachment-owner",
            password="pass-attachment-owner-123",
        )
        self.member = User.objects.create_user(
            username="attachment-member",
            password="pass-attachment-member-123",
        )
        self.outsider = User.objects.create_user(
            username="attachment-outsider",
            password="pass-attachment-outsider-123",
        )

        self.room = ChatRoom.objects.create(
            name="attachment-private-room",
            owner=self.owner,
            is_private=True,
        )
        self.room.members.add(self.owner)
        self.room.members.add(self.member)

        upload = SimpleUploadedFile(
            "secret.txt",
            b"secret chat attachment",
            content_type="text/plain",
        )

        self.message = Message.objects.create(
            user=self.owner,
            room=self.room,
            attachment=upload,
            attachment_type="file",
            attachment_name="secret.txt",
        )
        self.url = self.message.attachment.url

    def test_member_can_read_attachment(self):
        self.client.force_login(self.member)

        response = self.client.get(
            self.url,
            HTTP_HOST="testserver",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            b"".join(response.streaming_content),
            b"secret chat attachment",
        )
        self.assertEqual(
            response["X-Content-Type-Options"],
            "nosniff",
        )

    def test_non_member_cannot_read_attachment(self):
        self.client.force_login(self.outsider)

        response = self.client.get(
            self.url,
            HTTP_HOST="testserver",
        )

        self.assertEqual(response.status_code, 403)

    def test_anonymous_user_cannot_read_attachment(self):
        response = self.client.get(
            self.url,
            HTTP_HOST="testserver",
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    @override_settings(USE_NGINX_PROTECTED_MEDIA=True)
    def test_nginx_mode_uses_internal_accel_redirect(self):
        self.client.force_login(self.member)

        response = self.client.get(
            self.url,
            HTTP_HOST="testserver",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["X-Accel-Redirect"],
            "/_protected_chat_files/secret.txt",
        )
        self.assertEqual(
            response["X-Content-Type-Options"],
            "nosniff",
        )
