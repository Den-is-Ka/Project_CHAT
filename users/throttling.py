"""Rate limiting для входа и регистрации на основе Django cache.

Используется фиксированное временное окно; счётчики живут в кэше,
поэтому лимиты общие для всех процессов, когда кэш общий (Redis).
"""

import time
from functools import wraps
from ipaddress import ip_address

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse

DEFAULT_LIMIT = 10
DEFAULT_PERIOD = 300  # секунд


def _normalized_ip(value):
    """Нормализует IP-адрес или возвращает пустую строку."""

    try:
        return str(ip_address((value or "").strip()))
    except ValueError:
        return ""


def _client_ip(request):
    """Возвращает доверенный IP клиента для rate limiting.

    Прокси-заголовок учитывается только при явном включении режима
    доверенного reverse proxy. В Docker nginx перезаписывает
    X-Forwarded-For реальным адресом клиента.
    """

    remote_addr = _normalized_ip(request.META.get("REMOTE_ADDR"))

    if not settings.TRUST_PROXY_CLIENT_IP:
        return remote_addr

    forwarded = _normalized_ip(
        request.META.get("HTTP_X_FORWARDED_FOR")
    )

    return forwarded or remote_addr


def _rate_limit_allows(cache_key, limit, period):
    """Атомарно учитывает запрос в текущем временном окне."""

    timeout = period + 10

    if cache.add(cache_key, 1, timeout=timeout):
        return True

    try:
        count = cache.incr(cache_key)
    except ValueError:
        if cache.add(cache_key, 1, timeout=timeout):
            return True

        try:
            count = cache.incr(cache_key)
        except ValueError:
            return False

    return count <= limit


def rate_limit(key, limit=DEFAULT_LIMIT, period=DEFAULT_PERIOD, message=""):
    """Ограничивает число обращений к view за период.

    `key` — вызываемое: (request) -> str (часть ключа кэша).
    """

    def decorator(view):
        @wraps(view)
        def _wrapped(request, *args, **kwargs):
            window = int(time.time()) // period
            cache_key = f"throttle:{key(request)}:{window}"

            if not _rate_limit_allows(
                cache_key,
                limit,
                period,
            ):
                return JsonResponse(
                    {
                        "success": False,
                        "error": message or (f"Превышен лимит запросов. " f"Повторите через {period} секунд."),
                    },
                    status=429,
                )

            return view(request, *args, **kwargs)

        return _wrapped

    return decorator


def throttle_login(view):
    """Лимит на попытки входа: 10 за 5 минут."""

    return rate_limit(
        key=lambda request: f"login:{_client_ip(request)}",
        limit=10,
        period=300,
        message="Слишком много попыток входа. Подождите 5 минут.",
    )(view)


def throttle_register(view):
    """Лимит на регистрации: 5 в час с одного адреса."""

    return rate_limit(
        key=lambda request: f"register:{_client_ip(request)}",
        limit=5,
        period=3600,
        message="Слишком много регистраций. Подождите час.",
    )(view)
