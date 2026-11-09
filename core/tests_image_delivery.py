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
            f"GET\ndogs/archive/001/dog.jpg\ncard\n{expires}".encode(),
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

    def test_public_search_uses_light_thumbnail_and_keeps_private_media_hidden(self):
        from registry.models import Dog, DogImage

        public = Dog.objects.create(
            name="Optimized Search Dog", slug="optimized-search-dog",
            is_public=True,
        )
        private = Dog.objects.create(
            name="Optimized Secret Dog", slug="optimized-secret-dog",
            is_public=False,
        )
        DogImage.objects.create(dog=public, image="dogs/fast-search.jpg")
        DogImage.objects.create(dog=private, image="dogs/private-only.jpg")
        result = self.client.get("/dogs/?q=Optimized")
        self.assertEqual(result.status_code, 200)
        self.assertContains(result, "Optimized Search Dog")
        self.assertContains(result, "/_thumb/dogs/fast-search.jpg?variant=thumb")
        self.assertContains(result, 'data-media-fallback="/media/dogs/fast-search.jpg"')
        self.assertNotContains(result, "Optimized Secret Dog")
        self.assertNotContains(result, "private-only.jpg")

    def test_public_dog_profile_and_lightbox_use_optimized_preview_with_original_fallback(self):
        from registry.models import Dog, DogImage

        dog = Dog.objects.create(
            name="Photo Preview Dog", slug="photo-preview-dog", is_public=True,
        )
        DogImage.objects.create(
            dog=dog, image="dogs/photo-preview.jpg", is_primary=True,
        )
        DogImage.objects.create(dog=dog, image="dogs/second-photo.jpg")
        response = self.client.get(f"/dogs/{dog.slug}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "/_thumb/dogs/photo-preview.jpg?variant=portrait")
        self.assertContains(response, 'rel="preload" as="image"')
        self.assertContains(response, 'data-photo-src="/media/dogs/photo-preview.jpg"')
        self.assertContains(response, 'data-media-fallback="/media/dogs/photo-preview.jpg"')
        lightbox = response.content.decode().split("data-dog-lightbox-image", 1)[1].split(">", 1)[0]
        self.assertIn("/_thumb/dogs/photo-preview.jpg?variant=portrait", lightbox)
        self.assertNotIn('src="/media/dogs/photo-preview.jpg"', lightbox)
        self.assertIn('data-media-fallback="/media/dogs/photo-preview.jpg"', lightbox)
        self.assertContains(response, "20261109-fast-gallery-v1")

    def test_home_first_public_photo_is_priority_loaded_without_full_size_download(self):
        from django.core.cache import caches
        from registry.models import Dog, DogImage

        dog = Dog.objects.create(
            name="High Priority Photo", slug="high-priority-photo",
            is_public=True, search_count=900,
        )
        DogImage.objects.create(
            dog=dog, image="dogs/home-priority.jpg", is_primary=True,
        )
        caches["public"].delete("cca:home:featured-dog-ids:v1")
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "High Priority Photo")
        self.assertContains(page, 'rel="preload" as="image"')
        self.assertContains(page, "/_thumb/dogs/home-priority.jpg?variant=card")
        self.assertContains(page, 'fetchpriority="high"')
        self.assertContains(page, 'loading="eager"')
        self.assertContains(page, "480w")
        self.assertContains(page, "960w")
        self.assertContains(page, 'imagesizes="(max-width: 760px) 40vw')
        self.assertContains(page, 'sizes="(max-width: 760px) 40vw')
        self.assertNotContains(page, 'src="/media/dogs/home-priority.jpg"')
