from io import BytesIO
from unittest.mock import patch
import urllib.error

from django.test import SimpleTestCase, override_settings

from core.r2_gateway_storage import CloudflareR2GatewayStorage


@override_settings(SECRET_KEY="r2-retry-test-secret")
class R2GatewayRetryTests(SimpleTestCase):
    def test_transient_gateway_error_is_retried(self):
        storage = CloudflareR2GatewayStorage(
            base_url="https://media.example.test",
            timeout=1,
        )
        transient = urllib.error.HTTPError(
            "https://media.example.test/_r2/dogs/test.jpg",
            503,
            "Service unavailable",
            hdrs=None,
            fp=None,
        )

        with (
            patch(
                "core.r2_gateway_storage.urllib.request.urlopen",
                side_effect=[transient, BytesIO(b"ok")],
            ) as urlopen,
            patch("core.r2_gateway_storage.time.sleep") as sleep,
        ):
            response = storage._request("dogs/test.jpg", method="HEAD")

        self.assertEqual(response.read(), b"ok")
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(0.25)

    def test_forbidden_gateway_error_is_not_retried(self):
        storage = CloudflareR2GatewayStorage(
            base_url="https://media.example.test",
            timeout=1,
        )
        forbidden = urllib.error.HTTPError(
            "https://media.example.test/_r2/dogs/test.jpg",
            403,
            "Forbidden",
            hdrs=None,
            fp=None,
        )

        with (
            patch(
                "core.r2_gateway_storage.urllib.request.urlopen",
                side_effect=forbidden,
            ) as urlopen,
            patch("core.r2_gateway_storage.time.sleep") as sleep,
        ):
            with self.assertRaises(urllib.error.HTTPError):
                storage._request("dogs/test.jpg", method="HEAD")

        self.assertEqual(urlopen.call_count, 1)
        sleep.assert_not_called()
