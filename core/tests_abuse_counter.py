"""Rate-limit counters remain atomic under parallel worker requests."""
from concurrent.futures import ThreadPoolExecutor
from tempfile import TemporaryDirectory

from django.conf import settings
from django.core.cache import caches
from django.test import SimpleTestCase, override_settings

from core.abuse_counter import increment_abuse_counter
from core.middleware import AbuseProtectionMiddleware


class SharedAbuseCounterTests(SimpleTestCase):
    def test_parallel_workers_observe_one_shared_counter(self):
        with TemporaryDirectory() as temp:
            config = {
                **settings.CACHES,
                "abuse": {
                    "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
                    "LOCATION": temp,
                    "TIMEOUT": 300,
                    "OPTIONS": {"MAX_ENTRIES": 1000},
                },
            }
            with override_settings(CACHES=config):
                caches["abuse"].clear()
                with ThreadPoolExecutor(max_workers=10) as pool:
                    observed = list(pool.map(
                        lambda _: increment_abuse_counter("shared-limit", 600),
                        range(35),
                    ))
                self.assertEqual(sorted(observed), list(range(1, 36)))

    def test_public_login_uses_shared_counter_and_rejects_11th_post(self):
        with TemporaryDirectory() as temp:
            config = {
                **settings.CACHES,
                "abuse": {
                    "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
                    "LOCATION": temp,
                },
            }
            with override_settings(CACHES=config):
                from django.test import RequestFactory
                from django.http import HttpResponse

                guard = AbuseProtectionMiddleware(lambda request: HttpResponse("passed"))
                for i in range(10):
                    request = RequestFactory().post("/accounts/login/")
                    request.META["REMOTE_ADDR"] = "192.0.2.44"
                    self.assertEqual(guard(request).status_code, 200)
                request = RequestFactory().post("/accounts/login/")
                request.META["REMOTE_ADDR"] = "192.0.2.44"
                blocked = guard(request)
                self.assertEqual(blocked.status_code, 429)
                self.assertEqual(blocked["Retry-After"], "600")

    def test_development_cache_remains_available_without_extra_alias(self):
        config = {key: value for key, value in settings.CACHES.items() if key != "abuse"}
        with override_settings(CACHES=config):
            self.assertEqual(increment_abuse_counter("dev-fallback", 60), 1)
