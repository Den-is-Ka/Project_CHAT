from django.contrib.auth import get_user_model
from django.test import TestCase

from .forms import RegistrationForm

User = get_user_model()

VALID_PASSWORD = "strong-pass-123"


class RegistrationFormTests(TestCase):
    def setUp(self):
        self.data = {
            "username": "newuser",
            "email": "new@example.com",
            "password": VALID_PASSWORD,
            "password_confirm": VALID_PASSWORD,
        }

    def test_valid_registration(self):
        form = RegistrationForm(data=self.data)
        self.assertTrue(form.is_valid())

    def test_weak_password_rejected(self):
        data = dict(
            self.data,
            password="123",
            password_confirm="123",
        )
        form = RegistrationForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn("password", form.errors)

    def test_password_similar_to_username_rejected(self):
        data = dict(
            self.data,
            password="newuser1",
            password_confirm="newuser1",
        )
        form = RegistrationForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn("password", form.errors)

    def test_password_common_rejected(self):
        data = dict(
            self.data,
            password="password",
            password_confirm="password",
        )
        form = RegistrationForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn("password", form.errors)

    def test_duplicate_email_rejected(self):
        User.objects.create_user(
            username="existing",
            email="new@example.com",
            password=VALID_PASSWORD,
        )
        form = RegistrationForm(data=self.data)
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)

    def test_missing_email_rejected(self):
        data = dict(self.data, email="")
        form = RegistrationForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)


class LoginThrottleTests(TestCase):
    def setUp(self):
        User.objects.create_user(
            username="ivan",
            email="ivan@example.com",
            password="correct-pass-123",
        )

    def test_login_throttled_after_many_attempts(self):
        for _ in range(10):
            response = self.client.post(
                "/users/login/",
                {"username": "ivan", "password": "wrong"},
            )
            self.assertEqual(response.status_code, 400)

        response = self.client.post(
            "/users/login/",
            {"username": "ivan", "password": "wrong"},
        )
        self.assertEqual(response.status_code, 429)