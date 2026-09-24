import os

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from chat.models import ChatRoom

User = get_user_model()


def _required_seed_credentials():
    """Возвращает явно заданные и валидные учётные данные seed-пользователя."""

    username = (os.getenv("SEED_ADMIN_USERNAME") or "").strip()
    password = os.getenv("SEED_ADMIN_PASSWORD") or ""

    if not username or not password:
        raise CommandError(
            "Пустая база: задайте SEED_ADMIN_USERNAME и "
            "SEED_ADMIN_PASSWORD. Предсказуемые значения по умолчанию "
            "отключены."
        )

    candidate = User(username=username)

    try:
        validate_password(password, user=candidate)
    except ValidationError as exc:
        raise CommandError(
            "SEED_ADMIN_PASSWORD не проходит политику паролей: "
            + "; ".join(exc.messages)
        ) from exc

    return username, password


class Command(BaseCommand):
    """Идемпотентная инициализация данных для первого запуска.

    Если в базе нет пользователей, начальный пользователь создаётся только
    при явно заданных SEED_ADMIN_USERNAME и SEED_ADMIN_PASSWORD. Пароль
    проверяется стандартными валидаторами Django; небезопасных значений по
    умолчанию нет.

    Если пользователей уже есть, seed-учётные данные не требуются. При
    отсутствии комнат создаётся публичная комната "general" с первым
    существующим пользователем в роли владельца.
    """

    help = "Создаёт начального пользователя и комнату 'general' на пустой базе."

    def handle(self, *args, **options):
        seeded_user = None

        if not User.objects.exists():
            username, password = _required_seed_credentials()

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
