import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from chat.models import ChatRoom

User = get_user_model()


class Command(BaseCommand):
    """Идемпотентная инициализация данных для первого запуска.

    Если в базе нет пользователей — создаёт начального пользователя
    (по умолчанию admin/admin, меняется через SEED_ADMIN_USERNAME /
    SEED_ADMIN_PASSWORD). Если нет ни одной комнаты — создаёт
    публичную комнату "general".

    Без этого на пустой базе чат не открывается: first_chat не находит
    комнат и редиректит на главную, а комнату из интерфейса создать
    нечем (кнопка живёт внутри страницы чата).
    """

    help = "Создаёт начального пользователя и комнату 'general' на пустой базе."

    def handle(self, *args, **options):
        seeded_user = None

        if not User.objects.exists():
            username = os.getenv(
                "SEED_ADMIN_USERNAME",
                "admin",
            )
            password = os.getenv(
                "SEED_ADMIN_PASSWORD",
                "admin",
            )

            seeded_user = User.objects.create_user(
                username=username,
                password=password,
            )

            self.stdout.write(
                self.style.SUCCESS(
                    "Создан начальный пользователь "
                    f"'{username}' (пароль из SEED_ADMIN_PASSWORD)."
                )
            )
        else:
            self.stdout.write(
                "Пользователи уже есть — пропускаю."
            )

        if not ChatRoom.objects.exists():
            owner = seeded_user or User.objects.order_by("pk").first()

            room = ChatRoom.objects.create(
                name="general",
                owner=owner,
                description="Общая комната",
            )

            self.stdout.write(
                self.style.SUCCESS(
                    "Создана комната 'general'."
                )
            )
        else:
            self.stdout.write(
                "Комнаты уже есть — пропускаю."
            )