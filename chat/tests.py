import asyncio
from io import BytesIO
from unittest.mock import patch

from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TransactionTestCase

from PIL import Image

from . import consumers as consumers_module
from . import presence as presence_module
from .consumers import ChatConsumer
from .models import ChatRoom, Message, MessageReaction

User = get_user_model()


class ChatConsumerAccessTests(TransactionTestCase):
    """Доступ к чтению комнаты через WebSocket."""

    def setUp(self):
        self.owner = User.objects.create_user(
            username="owner",
            password="pass-owner-123",
        )
        self.member = User.objects.create_user(
            username="member",
            password="pass-member-123",
        )
        self.other = User.objects.create_user(
            username="other",
            password="pass-other-123",
        )
        self.room = ChatRoom.objects.create(
            name="public",
            owner=self.owner,
        )
        self.room.members.add(self.owner)

    def communicator(self, user, room_name):
        app = ChatConsumer.as_asgi()
        communicator = WebsocketCommunicator(
            app,
            f"/ws/chat/{room_name}/",
        )
        communicator.scope["user"] = user
        communicator.scope["url_route"] = {
            "args": (),
            "kwargs": {"room_name": room_name},
        }
        return communicator

    def run_loop(self, coro):
        """Запускает сценарий в одном цикле событий."""

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    async def receive_until_history(self, comm):
        for _ in range(5):
            message = await comm.receive_json_from(timeout=5)

            if message["type"] == "history":
                return message

        self.fail("История сообщений не была отправлена")

    async def connect_ok_scenario(self, user):
        comm = self.communicator(user, "public")
        connected, _ = await comm.connect()
        self.assertTrue(connected)
        await self.receive_until_history(comm)
        await comm.disconnect()

    def test_owner_can_connect(self):
        self.run_loop(self.connect_ok_scenario(self.owner))

    def test_member_can_connect(self):
        self.room.members.add(self.member)
        self.run_loop(self.connect_ok_scenario(self.member))

    async def connect_rejected_scenario(self, user):
        comm = self.communicator(user, "public")
        connected, _ = await comm.connect()
        self.assertFalse(connected)

    def test_non_member_cannot_connect_to_public_room(self):
        self.run_loop(self.connect_rejected_scenario(self.other))

    def test_non_member_cannot_connect_to_private_room(self):
        self.room.is_private = True
        self.room.save()
        self.room.members.add(self.member)
        self.run_loop(self.connect_rejected_scenario(self.other))


class SendMediaMessageViewTests(TransactionTestCase):
    """Загрузка файлов (фото, видео, аудио) в комнату."""

    def setUp(self):
        self.owner = User.objects.create_user(
            username="owner",
            password="pass-owner-123",
        )
        self.member = User.objects.create_user(
            username="member",
            password="pass-member-123",
        )
        self.other = User.objects.create_user(
            username="other",
            password="pass-other-123",
        )
        self.room = ChatRoom.objects.create(
            name="media-room",
            owner=self.owner,
        )
        self.room.members.add(self.owner)
        self.room.members.add(self.member)

    def make_image(self, name="photo.png"):
        buffer = BytesIO()
        image = Image.new("RGB", (2, 2), "#3366ff")
        image.save(buffer, format="PNG")
        buffer.seek(0)

        return SimpleUploadedFile(
            name,
            buffer.read(),
            content_type="image/png",
        )

    def upload(self, user, **data):
        self.client.force_login(user)

        return self.client.post(
            f"/chat/rooms/{self.room.id}/send_file/",
            data,
            HTTP_HOST="testserver",
        )

    def test_member_can_upload_image(self):
        response = self.upload(
            self.member,
            file=self.make_image(),
            caption="Привет с фото",
        )

        self.assertEqual(response.status_code, 201)

        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(
            data["message"]["attachment_type"],
            "image",
        )
        self.assertEqual(
            data["message"]["attachment_name"],
            "photo.png",
        )
        self.assertEqual(
            data["message"]["message"],
            "Привет с фото",
        )

        message = Message.objects.get(room=self.room)
        self.assertEqual(message.user, self.member)
        self.assertEqual(message.text, "Привет с фото")
        self.assertEqual(message.attachment_type, "image")
        self.assertTrue(message.attachment.name)

    def test_image_without_caption(self):
        response = self.upload(
            self.member,
            file=self.make_image(),
        )

        self.assertEqual(response.status_code, 201)

        message = Message.objects.get(room=self.room)
        self.assertEqual(message.text, "")
        self.assertEqual(message.attachment_type, "image")

    def test_video_attachment_type_detected(self):
        video = SimpleUploadedFile(
            "clip.mp4",
            b"fake mp4 bytes",
            content_type="video/mp4",
        )

        response = self.upload(
            self.member,
            file=video,
        )

        self.assertEqual(response.status_code, 201)

        message = Message.objects.get(room=self.room)
        self.assertEqual(message.attachment_type, "video")
        self.assertEqual(message.attachment_name, "clip.mp4")

    def test_audio_webm_detected(self):
        audio = SimpleUploadedFile(
            "voice_message_1.weba",
            b"fake opus bytes",
            content_type="audio/webm",
        )

        response = self.upload(
            self.member,
            file=audio,
        )

        self.assertEqual(response.status_code, 201)

        message = Message.objects.get(room=self.room)
        self.assertEqual(message.attachment_type, "audio")
        self.assertEqual(
            message.attachment_name,
            "voice_message_1.weba",
        )

    def test_audio_m4a_detected(self):
        audio = SimpleUploadedFile(
            "voice_message_1.m4a",
            b"fake m4a bytes",
            content_type="audio/mp4",
        )

        response = self.upload(
            self.member,
            file=audio,
        )

        self.assertEqual(response.status_code, 201)

        message = Message.objects.get(room=self.room)
        self.assertEqual(message.attachment_type, "audio")
        self.assertEqual(
            message.attachment_name,
            "voice_message_1.m4a",
        )

    def test_non_member_cannot_upload(self):
        response = self.upload(
            self.other,
            file=self.make_image(),
        )

        self.assertEqual(response.status_code, 403)

    def test_invalid_file_type_rejected(self):
        invalid = SimpleUploadedFile(
            "photo.png",
            b"This is not really a png file.",
            content_type="image/png",
        )

        response = self.upload(
            self.member,
            file=invalid,
        )

        self.assertEqual(response.status_code, 400)

        self.assertFalse(
            Message.objects.filter(
                room=self.room
            ).exists()
        )

    def test_anonymous_user_redirected_to_login(self):
        response = self.client.post(
            f"/chat/rooms/{self.room.id}/send_file/",
            {"file": self.make_image()},
            HTTP_HOST="testserver",
        )

        self.assertEqual(response.status_code, 302)

        self.assertIn(
            "/accounts/login/",
            response.url,
        )


class RoomMediaViewTests(TransactionTestCase):
    """Панель «Медиа»: группировка файлов и ссылок."""

    def setUp(self):
        self.owner = User.objects.create_user(
            username="media-owner",
            password="pass-owner-123",
        )
        self.member = User.objects.create_user(
            username="media-member",
            password="pass-member-123",
        )
        self.other = User.objects.create_user(
            username="media-other",
            password="pass-other-123",
        )
        self.room = ChatRoom.objects.create(
            name="media-gallery-room",
            owner=self.owner,
            is_private=True,
        )
        self.room.members.add(self.owner)
        self.room.members.add(self.member)

    def make_image(self, name="photo.png"):
        buffer = BytesIO()
        image = Image.new("RGB", (2, 2), "#3366ff")
        image.save(buffer, format="PNG")
        buffer.seek(0)

        return SimpleUploadedFile(
            name,
            buffer.read(),
            content_type="image/png",
        )

    def make_video(self, name="clip.mp4"):
        return SimpleUploadedFile(
            name,
            b"fake mp4 bytes",
            content_type="video/mp4",
        )

    def make_file(self, name="notes.txt"):
        return SimpleUploadedFile(
            name,
            b"document body",
            content_type="text/plain",
        )

    def upload(self, user, **data):
        self.client.force_login(user)

        return self.client.post(
            f"/chat/rooms/{self.room.id}/send_file/",
            data,
            HTTP_HOST="testserver",
        )

    def get_media(self, user):
        self.client.force_login(user)

        return self.client.get(
            f"/chat/rooms/{self.room.id}/media/",
            HTTP_HOST="testserver",
        )

    def test_anonymous_user_redirected_to_login(self):
        response = self.client.get(
            f"/chat/rooms/{self.room.id}/media/",
            HTTP_HOST="testserver",
        )

        self.assertEqual(response.status_code, 302)

        self.assertIn(
            "/accounts/login/",
            response.url,
        )

    def test_media_grouped_by_category(self):
        self.upload(
            self.member,
            file=self.make_image("sunset.png"),
            caption="Закат",
        )
        self.upload(
            self.member,
            file=self.make_video(),
            caption="Мой клип",
        )
        self.upload(
            self.member,
            file=self.make_file(),
        )

        Message.objects.create(
            user=self.member,
            room=self.room,
            text="Смотри https://example.com/awesome",
        )

        response = self.get_media(self.member)

        self.assertEqual(response.status_code, 200)

        data = response.json()

        self.assertEqual(len(data["photos"]), 1)
        self.assertEqual(
            data["photos"][0]["attachment_name"],
            "sunset.png",
        )

        self.assertEqual(len(data["videos"]), 1)
        self.assertEqual(
            data["videos"][0]["attachment_name"],
            "clip.mp4",
        )

        self.assertEqual(len(data["documents"]), 1)
        self.assertEqual(
            data["documents"][0]["attachment_name"],
            "notes.txt",
        )

        self.assertEqual(len(data["links"]), 1)
        self.assertEqual(
            data["links"][0]["link"],
            "https://example.com/awesome",
        )

    def test_private_room_non_member_forbidden(self):
        response = self.get_media(self.other)

        self.assertEqual(response.status_code, 403)

    def test_empty_room_returns_empty_categories(self):
        response = self.get_media(self.member)

        self.assertEqual(response.status_code, 200)

        data = response.json()

        self.assertEqual(data["photos"], [])
        self.assertEqual(data["videos"], [])
        self.assertEqual(data["documents"], [])
        self.assertEqual(data["links"], [])


class ChatConsumerReconnectTests(TransactionTestCase):
    """Стабильность соединения: переподключение, grace, heartbeat."""

    GRACE = 1

    def setUp(self):
        from django.core.cache import cache

        # Метки grace живут дольше самих тестов (TTL маркера больше
        # grace-периода), поэтому чистим кэш, чтобы не протекали
        # между тестами.
        cache.clear()

        self.owner = User.objects.create_user(
            username="owner",
            password="pass-owner-123",
        )
        self.member = User.objects.create_user(
            username="member",
            password="pass-member-123",
        )
        self.room = ChatRoom.objects.create(
            name="stable",
            owner=self.owner,
        )
        self.room.members.add(self.owner)
        self.room.members.add(self.member)

        self.grace_patch = patch.object(
            presence_module,
            "RECONNECT_GRACE",
            self.GRACE,
        )
        self.grace_patch.start()
        patch.object(
            consumers_module,
            "RECONNECT_GRACE",
            self.GRACE,
        ).start()
        self.addCleanup(
            patch.stopall
        )

    def communicator(self, user):
        app = ChatConsumer.as_asgi()
        communicator = WebsocketCommunicator(
            app,
            "/ws/chat/stable/",
        )
        communicator.scope["user"] = user
        communicator.scope["url_route"] = {
            "args": (),
            "kwargs": {"room_name": "stable"},
        }
        return communicator

    def run_loop(self, coro):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    async def receive_safe(self, comm, timeout=5):
        """Получает следующее сообщение, не убивая приложение.

        receive_json_from(c timeout=...) при таймауте отменяет задачу
        приложения, поэтому здесь мы дожидаемся появления сообщения
        в очереди и читаем без таймаута.
        """

        import time as _time

        deadline = _time.monotonic() + timeout

        while _time.monotonic() < deadline:

            if not comm.output_queue.empty():

                return await comm.receive_json_from()

            await asyncio.sleep(0.02)

        self.fail("Сообщение не получено за отведённое время")

    async def connect_until_history(self, comm):
        connected, _ = await comm.connect()
        self.assertTrue(connected)

        for _ in range(5):
            message = await self.receive_safe(comm)

            if message["type"] == "history":
                return

        self.fail("История не была отправлена")

    async def wait_for_status(self, comm, action, username, timeout=3):
        import time as _time

        deadline = _time.monotonic() + timeout

        while _time.monotonic() < deadline:
            message = await self.receive_safe(comm, timeout)

            if (
                message.get("type") == "user_status"
                and message.get("action") == action
                and message.get("username") == username
            ):
                return message

        self.fail(
            f"Событие {action} ({username}) не получено"
        )

    async def assert_no_status(self, comm, timeout):
        """Проверяет, что за окно не пришло join/leave для member."""

        import time as _time

        deadline = _time.monotonic() + timeout

        while _time.monotonic() < deadline:

            if not comm.output_queue.empty():

                message = await comm.receive_json_from()

                if (
                    message.get("type") == "user_status"
                    and message.get("username") == "member"
                ):
                    self.fail(
                        f"Неожиданный статус: {message}"
                    )

            else:

                await asyncio.sleep(0.1)

    def test_reconnect_without_join_announcement(self):
        async def scenario():
            owner_comm = self.communicator(self.owner)
            await self.connect_until_history(owner_comm)

            member_comm = self.communicator(self.member)
            await self.connect_until_history(member_comm)

            # Владелец видит вход участника.
            await self.wait_for_status(
                owner_comm,
                "join",
                "member",
            )

            # Разрываем соединение участника и быстро переподключаемся.
            await member_comm.disconnect()

            member_comm2 = self.communicator(self.member)
            await self.connect_until_history(member_comm2)

            # Повторного анонса входа быть не должно.
            await self.assert_no_status(
                owner_comm,
                self.GRACE + 1,
            )

            await member_comm2.disconnect()
            await owner_comm.disconnect()

            # Даём отложенным проверкам ухода доработать,
            # чтобы они не остались висеть при закрытии цикла.
            await asyncio.sleep(
                self.GRACE + 0.5
            )

        self.run_loop(scenario())

    def test_grace_expiry_broadcasts_leave(self):
        async def scenario():
            owner_comm = self.communicator(self.owner)
            await self.connect_until_history(owner_comm)

            member_comm = self.communicator(self.member)
            await self.connect_until_history(member_comm)

            await self.wait_for_status(
                owner_comm,
                "join",
                "member",
            )

            # Участник уходит и не возвращается.
            await member_comm.disconnect()

            # Спустя grace-период владелец получает "вышел из чата".
            await self.wait_for_status(
                owner_comm,
                "leave",
                "member",
            )

            await owner_comm.disconnect()

            await asyncio.sleep(
                self.GRACE + 0.5
            )

        self.run_loop(scenario())

    def test_ping_gets_pong(self):
        async def scenario():
            comm = self.communicator(self.owner)
            await self.connect_until_history(comm)

            # После истории могут идти online_users и т.п.
            await comm.send_json_to(
                {"type": "ping"}
            )

            for _ in range(5):
                message = await comm.receive_json_from(timeout=2)

                if message.get("type") == "pong":
                    break
            else:
                self.fail("pong не получен")

            await comm.disconnect()

            await asyncio.sleep(
                self.GRACE + 0.5
            )

        self.run_loop(scenario())

    def test_text_message_reaches_other_user_live(self):
        async def scenario():
            owner_comm = self.communicator(self.owner)
            await self.connect_until_history(owner_comm)

            member_comm = self.communicator(self.member)
            await self.connect_until_history(member_comm)

            # Отправляем текст через WebSocket.
            await member_comm.send_json_to(
                {"message": "живой текст"}
            )

            # Другой участник должен получить его сразу,
            # без перезагрузки страницы.
            received = False

            for _ in range(5):
                message = await self.receive_safe(owner_comm)

                if (
                    message.get("type") == "message"
                    and message.get("message") == "живой текст"
                ):
                    received = True
                    break

            self.assertTrue(received)

            # И отправитель тоже получает эхо.
            echoed = False

            for _ in range(5):
                message = await self.receive_safe(member_comm)

                if (
                    message.get("type") == "message"
                    and message.get("message") == "живой текст"
                ):
                    echoed = True
                    break

            self.assertTrue(echoed)

            await owner_comm.disconnect()
            await member_comm.disconnect()

            await asyncio.sleep(
                self.GRACE + 0.5
            )

        self.run_loop(scenario())

    def test_history_message_has_id(self):
        message = Message.objects.create(
            user=self.member,
            room=self.room,
            text="привет",
        )

        async def scenario():
            comm = self.communicator(self.owner)
            connected, _ = await comm.connect()
            self.assertTrue(connected)

            for _ in range(5):
                data = await comm.receive_json_from(timeout=5)

                if data["type"] == "history":
                    self.assertEqual(
                        data["messages"][0]["id"],
                        message.id,
                    )
                    break
            else:
                self.fail("История не получена")

            await comm.disconnect()

            await asyncio.sleep(
                self.GRACE + 0.5
            )

        self.run_loop(scenario())

    def test_reaction_on_own_message_rejected(self):
        message = Message.objects.create(
            user=self.owner,
            room=self.room,
            text="своё сообщение",
        )

        async def scenario():
            owner_comm = self.communicator(self.owner)
            await self.connect_until_history(owner_comm)

            await owner_comm.send_json_to(
                {
                    "type": "react",
                    "message_id": message.id,
                    "emoji": "👍",
                }
            )

            received = False

            for _ in range(5):
                data = await self.receive_safe(owner_comm)

                if data.get("type") != "error":
                    continue

                self.assertIn(
                    "свои сообщения",
                    data.get("message", ""),
                )

                received = True
                break

            self.assertTrue(received)

            reaction_count = await sync_to_async(
                lambda: MessageReaction.objects.filter(
                    message=message,
                ).count()
            )()

            self.assertEqual(
                reaction_count,
                0,
            )

            await owner_comm.disconnect()

            await asyncio.sleep(
                self.GRACE + 0.5
            )

        self.run_loop(scenario())

    def test_reply_on_own_message_rejected(self):
        message = Message.objects.create(
            user=self.owner,
            room=self.room,
            text="своё сообщение",
        )

        async def scenario():
            owner_comm = self.communicator(self.owner)
            await self.connect_until_history(owner_comm)

            await owner_comm.send_json_to(
                {
                    "type": "comment",
                    "reply_to_id": message.id,
                    "text": "ответ самому себе",
                }
            )

            received = False

            for _ in range(5):
                data = await self.receive_safe(owner_comm)

                if data.get("type") != "error":
                    continue

                self.assertIn(
                    "свои сообщения",
                    data.get("message", ""),
                )

                received = True
                break

            self.assertTrue(received)

            reply_exists = await sync_to_async(
                lambda: Message.objects.filter(
                    room=self.room,
                    reply_to=message,
                ).exists()
            )()

            self.assertFalse(
                reply_exists
            )

            await owner_comm.disconnect()

            await asyncio.sleep(
                self.GRACE + 0.5
            )

        self.run_loop(scenario())

    def test_reaction_reaches_other_user_live(self):
        message = Message.objects.create(
            user=self.owner,
            room=self.room,
            text="сообщение для реакции",
        )

        async def scenario():
            owner_comm = self.communicator(self.owner)
            await self.connect_until_history(owner_comm)

            member_comm = self.communicator(self.member)
            await self.connect_until_history(member_comm)

            # Участник ставит реакцию.
            await member_comm.send_json_to(
                {
                    "type": "react",
                    "message_id": message.id,
                    "emoji": "👍",
                }
            )

            received = False

            for _ in range(5):
                data = await self.receive_safe(owner_comm)

                if data.get("type") != "reaction":
                    continue

                if data.get("message_id") != message.id:
                    continue

                reactions = data.get("reactions") or []

                thumb = next(
                    (r for r in reactions if r["emoji"] == "👍"),
                    None,
                )

                self.assertIsNotNone(thumb)
                self.assertEqual(thumb["count"], 1)
                self.assertFalse(thumb.get("reacted_by_me"))

                received = True
                break

            self.assertTrue(received)

            await owner_comm.disconnect()
            await member_comm.disconnect()

            await asyncio.sleep(
                self.GRACE + 0.5
            )

        self.run_loop(scenario())

    def test_comment_reaches_other_user_live(self):
        message = Message.objects.create(
            user=self.owner,
            room=self.room,
            text="сообщение для комментария",
        )

        async def scenario():
            owner_comm = self.communicator(self.owner)
            await self.connect_until_history(owner_comm)

            member_comm = self.communicator(self.member)
            await self.connect_until_history(member_comm)

            await member_comm.send_json_to(
                {
                    "type": "comment",
                    "reply_to_id": message.id,
                    "text": "интересно!",
                }
            )

            received = False

            for _ in range(5):
                data = await self.receive_safe(owner_comm)

                if data.get("type") != "message":
                    continue

                reply_to = data.get("reply_to") or {}

                if reply_to.get("id") != message.id:
                    continue

                self.assertEqual(data["username"], "member")
                self.assertEqual(data["message"], "интересно!")
                self.assertEqual(
                    reply_to["message"],
                    "сообщение для комментария",
                )

                received = True
                break

            self.assertTrue(received)

            await owner_comm.disconnect()
            await member_comm.disconnect()

            await asyncio.sleep(
                self.GRACE + 0.5
            )

        self.run_loop(scenario())