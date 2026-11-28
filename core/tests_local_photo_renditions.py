"""Oracle local derivative safety and permissions."""
from pathlib import Path
from tempfile import TemporaryDirectory
from PIL import Image
from django.test import TestCase, override_settings
from registry.models import Dog, DogImage
from core.local_photo_renditions import build_previews, existing_preview
from core.templatetags.dog_images import dog_photo


class LocalPhotoRenditionTests(TestCase):
    def test_derivatives_preserve_original_and_access_control(self):
        with TemporaryDirectory() as root, override_settings(
            MEDIA_ROOT=root, MEDIA_EDGE_BASE_URL="", CCA_MEDIA_BACKEND="oracle-local",
            STORAGES={"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                      "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}},
        ):
            key = "dogs/local-test.jpg"
            path = Path(root, key)
            path.parent.mkdir()
            Image.new("RGB", (640, 320)).save(path, "JPEG")
            original = path.read_bytes()
            dog = Dog.objects.create(name="Local preview", slug="local-preview", is_public=True)
            DogImage.objects.create(dog=dog, image=key, is_primary=True)
            self.assertEqual(build_previews(key), 3)
            self.assertEqual(build_previews(key), 0)
            self.assertEqual(path.read_bytes(), original)
            self.assertIsNone(existing_preview("documents/private.jpg", "card"))
            url = dog_photo("/media/" + key, "card")
            self.assertEqual(url, "/media/" + key + "?variant=card")
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "image/webp")
            self.assertTrue(b"".join(response.streaming_content).startswith(b"RIFF"))
            response.close()
            Image.new("RGB", (320, 640), "red").save(path, "JPEG")
            self.assertIsNone(existing_preview(key, "card"))
            response = self.client.get(url)
            self.assertEqual(response["Content-Type"], "image/jpeg")
            response.close()
            dog.is_public = False
            dog.save(update_fields=["is_public"])
            self.assertEqual(self.client.get(url).status_code, 404)
