"""Safeguards for CPU-side WebP derivatives; no network or credentials needed."""
import io
import unittest
from PIL import Image

from scripts.backfill_r2_dog_webps import direct_key, is_dog_photo, make_webps


class WebpPhotoBackfillTests(unittest.TestCase):
    def test_never_optimize_documents_or_non_dog_paths(self):
        self.assertTrue(is_dog_photo("dogs/2026/11/dog.jpg"))
        for path in (
            "evidence/2026/11/photo.jpg",
            "documents/private.pdf",
            "dogs/../../documents/private.jpg",
            "dogs/archive/not-a-photo.txt",
            "other/photo.jpg",
        ):
            self.assertFalse(is_dog_photo(path), path)

    def test_stable_private_direct_key_matches_media_worker(self):
        path = "dogs/2026/11/IMG_6446.jpg"
        name = direct_key(path, "card")
        self.assertTrue(name.startswith("cca-photo-renditions/direct-v2/"))
        self.assertTrue(name.endswith("/card.webp"))
        self.assertEqual(len(name.split("/")[-2]), 64)
        self.assertNotIn(path, name)

    def test_convert_big_jpeg_into_uncropped_webp_variants(self):
        image = Image.new("RGB", (1320, 880), (89, 78, 64))
        output = io.BytesIO()
        image.save(output, "JPEG", quality=90)
        original = output.getvalue()
        variants = make_webps(original)
        self.assertEqual(set(variants), {"thumb", "card", "portrait"})
        self.assertEqual(original, output.getvalue())
        for name, size in (("thumb", (176, 117)), ("card", (480, 320)),
                           ("portrait", (960, 640))):
            self.assertTrue(variants[name].startswith(b"RIFF"))
            self.assertTrue(variants[name][8:12] == b"WEBP")
            with Image.open(io.BytesIO(variants[name])) as resized:
                self.assertEqual(resized.size, size)
            self.assertLess(len(variants[name]), len(original) * 2)

    def test_bad_bytes_do_not_modify_any_source(self):
        with self.assertRaises(ValueError):
            make_webps(b"")
        with self.assertRaises(Exception):
            make_webps(b"not-a-jpeg")


if __name__ == "__main__":
    unittest.main()
