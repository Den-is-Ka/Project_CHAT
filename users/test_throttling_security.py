from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, override_settings

from .throttling import _client_ip, _rate_limit_allows


class AuthThrottleSecurityTests(SimpleTestCase):
    """Регрессии безопасности rate limiting входа и регистрации."""

    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()

    def test_concurrent_requests_respect_atomic_limit(self):
        cache_key = "test:auth-throttle:atomic"

        def hit(_):
            return _rate_limit_allows(
                cache_key,
                limit=5,
                period=60,
            )

        with ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(hit, range(20)))

        self.assertEqual(sum(results), 5)

    @override_settings(TRUST_PROXY_CLIENT_IP=False)
    def test_untrusted_forwarded_header_is_ignored(self):
        request = self.factory.get(
            "/",
            REMOTE_ADDR="198.51.100.7",
            HTTP_X_FORWARDED_FOR="203.0.113.10",
        )

        self.assertEqual(
            _client_ip(request),
            "198.51.100.7",
        )

    @override_settings(TRUST_PROXY_CLIENT_IP=True)
    def test_trusted_proxy_ip_is_used(self):
        request = self.factory.get(
            "/",
            REMOTE_ADDR="172.20.0.5",
            HTTP_X_FORWARDED_FOR="203.0.113.10",
        )

        self.assertEqual(
            _client_ip(request),
            "203.0.113.10",
        )

    @override_settings(TRUST_PROXY_CLIENT_IP=True)
    def test_invalid_forwarded_chain_falls_back_to_remote_addr(self):
        request = self.factory.get(
            "/",
            REMOTE_ADDR="172.20.0.5",
            HTTP_X_FORWARDED_FOR=(
                "203.0.113.10, 198.51.100.7"
            ),
        )

        self.assertEqual(
            _client_ip(request),
            "172.20.0.5",
        )

    def test_nginx_overwrites_forwarded_ip(self):
        config = (
            settings.BASE_DIR / "nginx" / "nginx.conf"
        ).read_text(encoding="utf-8")

        self.assertNotIn(
            "$proxy_add_x_forwarded_for",
            config,
        )
        self.assertEqual(
            config.count(
                "proxy_set_header X-Forwarded-For $remote_addr;"
            ),
            3,
        )
