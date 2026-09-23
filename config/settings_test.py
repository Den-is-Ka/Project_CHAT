"""Изолированные настройки для запуска тестов."""

from .settings import *  # noqa: F401,F403

USE_REDIS = False

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    },
}

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    },
}
