from io import BytesIO

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.files.base import ContentFile

from .utils import resize_avatar

User = get_user_model()

MIN_PASSWORD_LENGTH = 8


class RegistrationForm(forms.ModelForm):
    """Форма регистрации пользователя."""

    password = forms.CharField(
        label="Пароль",
        widget=forms.PasswordInput,
        min_length=MIN_PASSWORD_LENGTH,
    )

    password_confirm = forms.CharField(
        label="Повторите пароль",
        widget=forms.PasswordInput,
    )

    class Meta:
        model = User
        fields = (
            "username",
            "email",
            "password",
            "password_confirm",
        )

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()

        if not email:
            raise forms.ValidationError("Укажите email.")

        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Пользователь с таким email уже существует.")

        return email

    def clean(self):
        cleaned_data = super().clean()

        password = cleaned_data.get("password")
        password_confirm = cleaned_data.get("password_confirm")

        if password and password_confirm and password != password_confirm:
            raise forms.ValidationError("Пароли не совпадают.")

        # Применяем системные валидаторы пароля
        # (AUTH_PASSWORD_VALIDATORS из settings).
        if password:
            user = self.instance
            user.username = cleaned_data.get("username", user.username)
            user.email = cleaned_data.get("email", user.email)

            try:
                validate_password(password, user=user)
            except forms.ValidationError as error:
                self.add_error("password", error)

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)

        user.set_password(self.cleaned_data["password"])

        if commit:
            user.save()

        return user


class ProfileForm(forms.ModelForm):
    """Форма редактирования профиля пользователя."""

    class Meta:
        model = User
        fields = (
            "username",
            "email",
            "avatar",
        )

        labels = {
            "username": "Имя пользователя",
            "email": "Email",
            "avatar": "Аватар",
        }

        widgets = {
            "username": forms.TextInput(
                attrs={
                    "placeholder": "Введите имя пользователя",
                }
            ),
            "email": forms.EmailInput(
                attrs={
                    "placeholder": "Введите email",
                }
            ),
        }

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()

        if not email:
            raise forms.ValidationError("Укажите email.")

        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Пользователь с таким email уже существует.")

        return email

    def clean_avatar(self):
        avatar = self.cleaned_data.get("avatar")

        if not avatar:
            return avatar

        try:
            resized_image = resize_avatar(avatar)
        except Exception:
            raise forms.ValidationError("Не удалось обработать изображение.")

        buffer = BytesIO()

        resized_image.save(
            buffer,
            format="JPEG",
            quality=90,
        )

        return ContentFile(
            buffer.getvalue(),
            name="avatar.jpg",
        )
