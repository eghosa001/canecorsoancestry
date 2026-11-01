"""Safe, fast public photo URLs: no bypass for private documents."""
from urllib.parse import parse_qs, urlsplit
import hashlib
import hmac

from django.test import TestCase, override_settings
from django.template import Context, Template

from core.templatetags.dog_images import dog_photo


@override_settings(
    MEDIA_EDGE_BASE_URL="https://r2.example.workers.dev",
    MEDIA_EDGE_URL_TTL=300,
    R2_GATEWAY_SIGNING_KEY="test-only-r2-photo-key",
)
class DogPhotoDeliveryTests(TestCase):
    def test_direct_r2_thumbnail_is_signed_for_exact_path_variant_and_expiry(self):
        result = dog_photo("/media/dogs/archive/001/dog.jpg?v=old", "card")
        parsed = urlsplit(result)
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.path, "/_thumb/dogs/archive/001/dog.jpg")
        self.assertEqual(query["variant"], ["card"])
        expires = query["expires"][0]
        expected = hmac.new(
            b"test-only-r2-photo-key",
            f"GET\\ndogs/archive/001/dog.jpg\\ncard\\n{expires}".encode(),
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(query["signature"], [expected])
        self.assertEqual(
            dog_photo("/media/dogs/archive/001/dog.jpg", "card"),
            dog_photo("/media/dogs/archive/001/dog.jpg", "card"),
        )

    def test_no_transform_of_private_documents_or_third_party_photos(self):
        for url in (
            "/media/documents/private.pdf",
            "/media/dogs/private-health-report.pdf",
            "/media/submissions/evidence.jpg",
            "https://www.canecorsopedigree.com/static/images/animal/001.jpg",
            "/media/dogs/%2e%2e/documents/private.jpg",
        ):
            self.assertEqual(dog_photo(url, "card"), url)
        self.assertEqual(
            dog_photo("/media/dogs/sample.jpg", "unknown"),
            "/media/dogs/sample.jpg",
        )

    @override_settings(MEDIA_EDGE_BASE_URL="")
    def test_local_development_uses_existing_storage_media_url(self):
        self.assertEqual(dog_photo("/media/dogs/a.jpg", "thumb"), "/media/dogs/a.jpg")

    def test_template_output_escapes_query_parameter_separators(self):
        result = Template(
            '{% load dog_images %}<img src="{{ value|dog_photo:"thumb" }}">'
        ).render(Context({"value": "/media/dogs/zeus.jpg"}))
        self.assertIn("/_thumb/dogs/zeus.jpg?variant=thumb&amp;expires=", result)
