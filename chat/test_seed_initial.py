import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from .models import ChatRoom

User = get_user_model()


class SeedInitialSecurityTests(TestCase):
    """seed_initial не должен создавать предсказуемые учётные данные."""

    @patch.dict(
        os.environ,
        {
            "SEED_ADMIN_USERNAME": "",
            "SEED_ADMIN_PASSWORD": "",
        },
    )
    def test_empty_database_requires_explicit_seed_credentials(self):
        with self.assertRaisesMessage(
            CommandError,
            "Пустая база: задайте SEED_ADMIN_USERNAME",
        ):
            call_command("seed_initial")

        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(ChatRoom.objects.count(), 0)

    @patch.dict(
        os.environ,
        {
            "SEED_ADMIN_USERNAME": "seed-admin",
            "SEED_ADMIN_PASSWORD": "A9!vK7#pQ2$mN8",
        },
    )
    def test_explicit_strong_credentials_create_user_and_general_room(self):
        call_command("seed_initial")

        user = User.objects.get(username="seed-admin")
        room = ChatRoom.objects.get(name="general")

        self.assertTrue(user.check_password("A9!vK7#pQ2$mN8"))
        self.assertEqual(room.owner, user)

    @patch.dict(
        os.environ,
        {
            "SEED_ADMIN_USERNAME": "seed-admin",
            "SEED_ADMIN_PASSWORD": "admin",
        },
    )
    def test_weak_seed_password_is_rejected(self):
        with self.assertRaisesMessage(
            CommandError,
            "SEED_ADMIN_PASSWORD не проходит политику паролей",
        ):
            call_command("seed_initial")

        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(ChatRoom.objects.count(), 0)

    @patch.dict(
        os.environ,
        {
            "SEED_ADMIN_USERNAME": "",
            "SEED_ADMIN_PASSWORD": "",
        },
    )
    def test_existing_user_does_not_require_seed_credentials(self):
        existing_user = User.objects.create_user(
            username="existing-user",
            password="ExistingPass-2026!",
        )

        call_command("seed_initial")

        self.assertEqual(User.objects.count(), 1)
        room = ChatRoom.objects.get(name="general")
        self.assertEqual(room.owner, existing_user)
