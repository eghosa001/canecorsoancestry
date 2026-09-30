from urllib.parse import parse_qs, urlparse

from django.test import TestCase, override_settings

from core.cloudflare_media import media_signature
from registry.models import Dog, DogImage


@override_settings(
    MEDIA_EDGE_BASE_URL="https://edge.example.workers.dev",
    MEDIA_EDGE_URL_TTL=300,
    SECRET_KEY="cloud-run-media-test-secret",
)
class CloudRunMediaDeliveryTests(TestCase):
    def setUp(self):
        self.dog = Dog.objects.create(
            name="Public Media Dog",
            slug="public-media-dog",
            is_public=True,
        )
        self.path = "dogs/example/public.jpg"
        DogImage.objects.create(
            dog=self.dog,
            image=self.path,
            is_primary=True,
        )

    def test_authorized_media_redirect_is_signed(self):
        response = self.client.get(f"/media/{self.path}")

        self.assertEqual(response.status_code, 302)
        parsed = urlparse(response["Location"])
        self.assertEqual(parsed.netloc, "edge.example.workers.dev")
        self.assertEqual(parsed.path, f"/_media/{self.path}")

        query = parse_qs(parsed.query)
        expires = query["expires"][0]
        signature = query["signature"][0]
        self.assertEqual(
            signature,
            media_signature(
                "cloud-run-media-test-secret",
                self.path,
                int(expires),
            ),
        )

    def test_private_dog_image_is_not_publicly_redirected(self):
        self.dog.is_public = False
        self.dog.save(update_fields=["is_public"])

        response = self.client.get(f"/media/{self.path}")

        self.assertEqual(response.status_code, 404)
