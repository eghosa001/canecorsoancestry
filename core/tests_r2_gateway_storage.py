from io import BytesIO
from unittest.mock import MagicMock, patch
import urllib.error

from django.core.files.base import ContentFile
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

    def test_save_exact_uses_worker_verified_put_response(self):
        storage = CloudflareR2GatewayStorage(
            base_url="https://media.example.test",
            timeout=1,
        )
        put_response = MagicMock()
        put_response.read.return_value = (
            b'{"status":"stored","key":"dogs/test.jpg","size":4,"r2_verified":true}'
        )
        put_response.__enter__.return_value = put_response
        put_response.__exit__.return_value = False

        with patch.object(storage, "_request", return_value=put_response) as request:
            saved = storage.save_exact("dogs/test.jpg", ContentFile(b"data"))

        self.assertEqual(saved, "dogs/test.jpg")
        request.assert_called_once()
        self.assertEqual(request.call_args.kwargs["method"], "PUT")

    def test_save_exact_rejects_unverified_worker_response(self):
        storage = CloudflareR2GatewayStorage(
            base_url="https://media.example.test",
            timeout=1,
        )
        put_response = MagicMock()
        put_response.read.return_value = (
            b'{"status":"stored","key":"dogs/test.jpg","size":4,"r2_verified":false}'
        )
        put_response.__enter__.return_value = put_response
        put_response.__exit__.return_value = False

        with patch.object(storage, "_request", return_value=put_response):
            with self.assertRaisesRegex(OSError, "could not verify"):
                storage.save_exact("dogs/test.jpg", ContentFile(b"data"))

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
