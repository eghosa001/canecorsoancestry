from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from core.cloudflare_media import media_signature
from registry.models import Dog, DogImage, Kennel, KennelMembership


@override_settings(
    MEDIA_EDGE_BASE_URL="https://edge.example.workers.dev",
    MEDIA_EDGE_URL_TTL=300,
    SECRET_KEY="r2-media-test-secret",
)
class R2MediaDeliveryTests(TestCase):
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
                "r2-media-test-secret",
                self.path,
                int(expires),
            ),
        )

    def test_private_dog_image_is_not_publicly_redirected(self):
        self.dog.is_public = False
        self.dog.save(update_fields=["is_public"])

        response = self.client.get(f"/media/{self.path}")

        self.assertEqual(response.status_code, 404)

    def test_member_can_view_private_photo_for_linked_kennel_dog(self):
        kennel = Kennel.objects.create(name="Member Media Kennel", slug="member-media")
        self.dog.kennel = kennel
        self.dog.is_public = False
        self.dog.save(update_fields=["kennel", "is_public"])
        member = get_user_model().objects.create_user(
            username="private-media-member",
            password="test-pass-123",
        )
        KennelMembership.objects.create(
            user=member,
            kennel=kennel,
            role=KennelMembership.Role.OWNER,
        )
        self.client.force_login(member)

        response = self.client.get(f"/media/{self.path}")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/_media/", response["Location"])
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_signed_public_thumbnail_redirect_uses_optimized_variant(self):
        response = self.client.get(f"/media/{self.path}?variant=card")
        self.assertEqual(response.status_code, 302)
        parsed = urlparse(response["Location"])
        self.assertEqual(parsed.path, f"/_thumb/{self.path}")
        self.assertEqual(parse_qs(parsed.query)["variant"], ["card"])
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_private_member_thumbnail_is_signed_only_after_access_check(self):
        kennel = Kennel.objects.create(name="Private Image Kennel", slug="private-image")
        self.dog.kennel = kennel
        self.dog.is_public = False
        self.dog.save(update_fields=["kennel", "is_public"])
        # The same short-lived preview must not be obtainable anonymously.
        self.assertEqual(
            self.client.get(f"/media/{self.path}?variant=card").status_code,
            404,
        )
        member = get_user_model().objects.create_user(username="photo-member")
        KennelMembership.objects.create(
            user=member, kennel=kennel, role=KennelMembership.Role.OWNER,
        )
        self.client.force_login(member)
        response = self.client.get(f"/media/{self.path}?variant=card")
        self.assertEqual(response.status_code, 302)
        parsed = urlparse(response["Location"])
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.path, f"/_thumb/{self.path}")
        self.assertEqual(query["variant"], ["card"])
        self.assertEqual(response["Cache-Control"], "private, no-store")
        from core.templatetags.dog_images import dog_photo
        self.assertEqual(
            response["Location"],
            dog_photo(f"/media/{self.path}", "card"),
        )
        # Full-resolution original continues through the legacy private route.
        original = self.client.get(f"/media/{self.path}")
        self.assertEqual(urlparse(original["Location"]).path, f"/_media/{self.path}")
