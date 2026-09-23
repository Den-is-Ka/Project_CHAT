import asyncio
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TransactionTestCase

from . import consumers as consumers_module
from . import views as views_module
from .consumers import ChatConsumer
from .models import ChatRoom, Message, MessageReaction
from .rate_limit import rate_limit_allows

User = get_user_model()


class AtomicRateLimitTests(SimpleTestCase):
    """Атомарный счётчик не разрешает больше действий, чем задано."""

    def setUp(self):
        cache.clear()

    def test_concurrent_hits_respect_limit(self):
        limit = 5

        def hit(_):
            return rate_limit_allows(
                key_prefix="test:rate:concurrent",
                limit=limit,
                window_seconds=60,
            )

        with ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(hit, range(20)))

        self.assertEqual(sum(results), limit)


class UploadRateLimitTests(TransactionTestCase):
    """HTTP-загрузки используют общий атомарный rate limit."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="upload-rate-user",
            password="pass-upload-rate-123",
        )
        self.room = ChatRoom.objects.create(
            name="upload-rate-room",
            owner=self.user,
        )
        self.room.members.add(self.user)
        self.client.force_login(self.user)

    def upload(self, name):
        file = SimpleUploadedFile(
            name,
            b"document body",
            content_type="text/plain",
        )

        return self.client.post(
            f"/chat/rooms/{self.room.id}/send_file/",
            {"file": file},
            HTTP_HOST="testserver",
        )

    @patch.object(views_module, "MAX_MEDIA_UPLOADS", 1)
    def test_second_upload_is_blocked(self):
        first = self.upload("first.txt")
        second = self.upload("second.txt")

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(
            Message.objects.filter(room=self.room).count(),
            1,
        )


class WebSocketRateLimitTests(TransactionTestCase):
    """Реакции и комментарии не обходят лимит обычных сообщений."""

    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user(
            username="rate-owner",
            password="pass-rate-owner-123",
        )
        self.member = User.objects.create_user(
            username="rate-member",
            password="pass-rate-member-123",
        )
        self.room = ChatRoom.objects.create(
            name="rate-room",
            owner=self.owner,
        )
        self.room.members.add(self.owner)
        self.room.members.add(self.member)
        self.original = Message.objects.create(
            user=self.owner,
            room=self.room,
            text="исходное сообщение",
        )

        self.limit_patch = patch.object(
            consumers_module,
            "SEND_RATE_LIMIT",
            1,
        )
        self.limit_patch.start()
        self.addCleanup(self.limit_patch.stop)

    def run_loop(self, coro):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            return loop.run_until_complete(coro)
        finally:
            pending = [
                task
                for task in asyncio.all_tasks(loop)
                if not task.done()
            ]

            for task in pending:
                task.cancel()

            if pending:
                loop.run_until_complete(
                    asyncio.gather(
                        *pending,
                        return_exceptions=True,
                    )
                )

            loop.run_until_complete(loop.shutdown_asyncgens())
            asyncio.set_event_loop(None)
            loop.close()

    def communicator(self):
        communicator = WebsocketCommunicator(
            ChatConsumer.as_asgi(),
            f"/ws/chat/{self.room.name}/",
        )
        communicator.scope["user"] = self.member
        communicator.scope["url_route"] = {
            "args": (),
            "kwargs": {"room_name": self.room.name},
        }
        return communicator

    async def receive_until_type(self, communicator, expected_type):
        for _ in range(10):
            message = await communicator.receive_json_from(timeout=5)

            if message.get("type") == expected_type:
                return message

        self.fail(f"Сообщение типа {expected_type} не получено")

    async def connect_until_history(self, communicator):
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        await self.receive_until_type(communicator, "history")

    async def consume_one_text_message(self, communicator):
        await communicator.send_json_to({"message": "первое действие"})
        message = await self.receive_until_type(communicator, "message")
        self.assertEqual(message.get("message"), "первое действие")

    def test_reaction_cannot_bypass_text_rate_limit(self):
        async def scenario():
            communicator = self.communicator()
            await self.connect_until_history(communicator)

            try:
                await self.consume_one_text_message(communicator)
                await communicator.send_json_to(
                    {
                        "type": "react",
                        "message_id": self.original.id,
                        "emoji": "👍",
                    }
                )

                error = await self.receive_until_type(
                    communicator,
                    "error",
                )
                self.assertIn("Слишком много сообщений", error["message"])
            finally:
                await communicator.disconnect()

        self.run_loop(scenario())

        self.assertFalse(
            MessageReaction.objects.filter(
                message=self.original,
                user=self.member,
            ).exists()
        )

    def test_comment_cannot_bypass_text_rate_limit(self):
        async def scenario():
            communicator = self.communicator()
            await self.connect_until_history(communicator)

            try:
                await self.consume_one_text_message(communicator)
                await communicator.send_json_to(
                    {
                        "type": "comment",
                        "reply_to_id": self.original.id,
                        "text": "второе действие",
                    }
                )

                error = await self.receive_until_type(
                    communicator,
                    "error",
                )
                self.assertIn("Слишком много сообщений", error["message"])
            finally:
                await communicator.disconnect()

        self.run_loop(scenario())

        self.assertFalse(
            Message.objects.filter(
                room=self.room,
                user=self.member,
                reply_to=self.original,
            ).exists()
        )
