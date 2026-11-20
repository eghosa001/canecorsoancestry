"""Oracle-hosted photos must obey the existing media access rules."""

from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import TestCase, override_settings

from registry.models import Dog, DogImage


class OracleMediaDeliveryTests(TestCase):
    def test_public_photo_is_served_from_disk_and_private_photo_is_not(self):
        with TemporaryDirectory() as root:
            storage = {
                "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                "staticfiles": {
                    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
                },
            }
            with override_settings(
                STORAGES=storage,
                MEDIA_ROOT=root,
                MEDIA_EDGE_BASE_URL="",
                CCA_MEDIA_BACKEND="oracle-local",
            ):
                photo = Path(root, "dogs", "public.jpg")
                photo.parent.mkdir(parents=True, exist_ok=True)
                photo.write_bytes(b"photo-bytes")

                public = Dog.objects.create(
                    name="Oracle Public Dog",
                    slug="oracle-public-dog",
                    is_public=True,
                )
                private = Dog.objects.create(
                    name="Oracle Private Dog",
                    slug="oracle-private-dog",
                    is_public=False,
                )
                DogImage.objects.create(
                    dog=public, image="dogs/public.jpg", is_primary=True
                )
                DogImage.objects.create(
                    dog=private, image="dogs/private.jpg", is_primary=True
                )

                response = self.client.get("/media/dogs/public.jpg")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(b"".join(response.streaming_content), b"photo-bytes")
                self.assertEqual(response["Cache-Control"], "public, max-age=86400")

                self.assertEqual(
                    self.client.get("/media/dogs/private.jpg").status_code, 404
                )
                self.assertEqual(
                    self.client.get("/media/dogs/missing.jpg").status_code, 404
                )

    @override_settings(MEDIA_EDGE_BASE_URL="")
    def test_oracle_mode_never_generates_signed_r2_links(self):
        from core.templatetags.dog_images import dog_photo

        self.assertEqual(
            dog_photo("/media/dogs/public.jpg", "card"),
            "/media/dogs/public.jpg",
        )
