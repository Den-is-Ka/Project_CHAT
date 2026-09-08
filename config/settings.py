import os
from pathlib import Path

from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv()

SECRET_KEY = os.getenv('SECRET_KEY')

if not SECRET_KEY:
    raise ValueError('SECRET_KEY not set')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', False) == 'True'

ALLOWED_HOSTS = os.getenv(
    "ALLOWED_HOSTS",
    "127.0.0.1,localhost,[::1]",
).split(",")

CSRF_TRUSTED_ORIGINS = os.getenv(
    "CSRF_TRUSTED_ORIGINS",
    "http://127.0.0.1:8000,http://localhost:8000",
).split(",")

# Application definition

INSTALLED_APPS = [
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'channels',
    'chat',
    'users',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            BASE_DIR / 'templates',
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'


# Database
# https://docs.djangoproject.com/en/6.1/ref/settings/#databases

# Где лежит SQLite-файл. В Docker настраивается на постоянный каталог,
# чтобы WAL-файлы (-wal/-shm) сохранялись между перезапусками.
DB_PATH = os.getenv(
    "DB_PATH",
    str(BASE_DIR / "db.sqlite3"),
)

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': DB_PATH,
        'OPTIONS': {
            # Снижает ошибки «database is locked» при конкурентных записях.
            'timeout': 20,
            # WAL: читатели не блокируют записывающего и наоборот.
            'init_command': ('PRAGMA journal_mode=WAL;' 'PRAGMA synchronous=NORMAL;'),
            # BEGIN IMMEDIATE берёт RESERVED lock сразу, без
            # дедлока при апгрейде отложенной транзакции.
            'transaction_mode': 'IMMEDIATE',
        },
    }
}


# Password validation
# https://docs.djangoproject.com/en/6.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.1/topics/i18n/

LANGUAGE_CODE = 'ru'

TIME_ZONE = 'Europe/Moscow'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.1/howto/static-files/

STATIC_URL = "/static/"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

STATICFILES_DIRS = [
    BASE_DIR / "static",
]

STATIC_ROOT = BASE_DIR / "staticfiles"


# Email
# https://docs.djangoproject.com/en/6.1/topics/email/#topic-email-configuration

EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend",
)


AUTH_USER_MODEL = 'users.User'

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

# Использовать Redis для каналов WebSocket и кэша.
# Включается в docker-compose (несколько процессов/workers).
USE_REDIS = os.getenv("USE_REDIS_CHANNEL_LAYER", "False") == "True"

if USE_REDIS:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": f"redis://{REDIS_HOST}:{REDIS_PORT}/1",
        },
    }

    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [(REDIS_HOST, REDIS_PORT)],
            },
        },
    }
else:
    # Локальная разработка: формат InMemory работает в одном процессе.
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


# Безопасность продакшена (за SSL-терминатором, например nginx).
# Включите USE_HTTPS=True в production: добавляются HSTS, secure-cookies,
# редирект на HTTPS. Для локальной разработки всё остаётся выключенным.
if os.getenv("USE_HTTPS", "False") == "True":
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", 0))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
