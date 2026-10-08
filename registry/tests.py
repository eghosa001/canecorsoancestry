from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from pedigrees.services import profile_direct_relations

from .models import Dog, DogDocument, DogImage, DogRegistration, DogSource, DogTitle, HealthRecord, Kennel, Litter, RegistrationAuthority, VerificationState
from .services import duplicate_candidates
from .views import _public_profile_dog


class DogModelTests(TestCase):
    def test_dog_cannot_be_its_own_parent(self):
        dog = Dog.objects.create(name="Karma", slug="karma")
        dog.sire = dog
        with self.assertRaises(ValidationError):
            dog.full_clean()

    def test_public_search_finds_dog_by_name(self):
        dog = Dog.objects.create(name="Karma Custodi Nos", slug="karma-custodi-nos", is_public=True)
        DogImage.objects.create(dog=dog, image="dogs/karma.jpg", is_primary=True)
        response = self.client.get(reverse("registry:dog-search"), {"q": "Karma"})
        self.assertContains(response, "Karma Custodi Nos")

    def test_public_search_is_paginated(self):
        for index in range(25):
            dog = Dog.objects.create(
                name=f"Paged Dog {index:02d}",
                slug=f"paged-dog-{index:02d}",
                is_public=True,
            )
            DogImage.objects.create(dog=dog, image=f"dogs/paged-{index:02d}.jpg")

        response = self.client.get(reverse("registry:dog-search"), {"q": "Paged Dog"})

        self.assertEqual(response.context["result_count"], 25)
        self.assertEqual(len(response.context["dogs"]), 18)
        self.assertTrue(response.context["page_obj"].has_next())

    def test_duplicate_candidates_skip_very_common_name_buckets(self):
        for index in range(9):
            Dog.objects.create(name="Atlas", slug=f"atlas-{index}")

        Dog.objects.create(name="Rare Twin", slug="rare-twin-a")
        Dog.objects.create(name="Rare Twin", slug="rare-twin-b")

        rows = duplicate_candidates(limit=10)

        self.assertTrue(
            any(
                row["reference"].name == "Rare Twin"
                and row["candidate"].name == "Rare Twin"
                for row in rows
            )
        )
        self.assertFalse(
            any(
                row["reference"].name == "Atlas"
                or row["candidate"].name == "Atlas"
                for row in rows
            )
        )

    def test_search_origin_profile_still_records_popularity(self):
        dog = Dog.objects.create(
            name="Search Counter Dog",
            slug="search-counter-dog",
            is_public=True,
        )

        response = self.client.get(
            reverse("registry:dog-detail", args=[dog.slug]),
            {"source": "search"},
        )

        self.assertEqual(response.status_code, 200)
        dog.refresh_from_db()
        self.assertEqual(dog.search_count, 1)

    def test_search_origin_popularity_throttles_repeat_writes(self):
        dog = Dog.objects.create(
            name="Throttled Search Dog",
            slug="throttled-search-dog",
            is_public=True,
        )
        throttle_key = f"cca:dog-search-hit:{dog.pk}"
        cache.delete(throttle_key)
        self.addCleanup(cache.delete, throttle_key)

        for _ in range(2):
            response = self.client.get(
                reverse("registry:dog-detail", args=[dog.slug]),
                {"source": "search"},
            )
            self.assertEqual(response.status_code, 200)

        dog.refresh_from_db()
        self.assertEqual(dog.search_count, 1)

    def test_default_browse_only_shows_imaged_dogs_by_popularity(self):
        kennel = Kennel.objects.create(name="Shared Kennel", slug="shared-kennel")
        popular = Dog.objects.create(
            name="Popular Imaged Dog",
            slug="popular-imaged-dog",
            kennel=kennel,
            is_public=True,
            search_count=50,
        )
        same_kennel = Dog.objects.create(
            name="Second Shared Kennel Dog",
            slug="second-shared-kennel-dog",
            kennel=kennel,
            is_public=True,
            search_count=20,
        )
        quieter = Dog.objects.create(
            name="Quieter Imaged Dog",
            slug="quieter-imaged-dog",
            is_public=True,
            search_count=3,
        )
        Dog.objects.create(
            name="No Image Dog",
            slug="no-image-dog",
            is_public=True,
            search_count=500,
        )
        DogImage.objects.create(dog=popular, image="dogs/popular.jpg", is_primary=True)
        DogImage.objects.create(dog=same_kennel, image="dogs/shared-second.jpg", is_primary=True)
        DogImage.objects.create(dog=quieter, image="dogs/quieter.jpg", is_primary=True)

        response = self.client.get(reverse("registry:dog-search"))

        self.assertEqual(
            [dog.name for dog in response.context["dogs"]],
            ["Popular Imaged Dog", "Quieter Imaged Dog"],
        )
        self.assertNotContains(response, "Second Shared Kennel Dog")
        self.assertNotContains(response, "No Image Dog")

    def test_public_search_includes_trusted_source_photo_without_managed_copy(self):
        dog = Dog.objects.create(
            name="Source Image Search Dog",
            slug="source-image-search-dog",
            is_public=True,
        )
        DogSource.objects.create(
            dog=dog,
            source_url="https://canecorsopedigree.com/dog/source-image-search-dog",
            raw_payload={
                "image_url": "https://canecorsopedigree.com/static/images/animal/source-image.jpg"
            },
        )

        response = self.client.get(
            reverse("registry:dog-search"),
            {"q": "Source Image Search"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Source Image Search Dog")
        self.assertContains(
            response,
            "https://canecorsopedigree.com/static/images/animal/source-image.jpg",
        )

    def test_public_search_excludes_untrusted_source_url_without_managed_photo(self):
        dog = Dog.objects.create(
            name="Untrusted Source Dog",
            slug="untrusted-source-dog",
            is_public=True,
        )
        DogSource.objects.create(
            dog=dog,
            source_url="https://example.com/dog/untrusted-source-dog",
            raw_payload={"image_url": "https://example.com/untrusted.jpg"},
        )

        response = self.client.get(
            reverse("registry:dog-search"),
            {"q": "Untrusted Source"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Untrusted Source Dog")

    def test_authenticated_profile_secondary_actions_are_grouped(self):
        user = get_user_model().objects.create_user(
            username="profile-reviewer-member",
            password="test-pass-123",
        )
        dog = Dog.objects.create(
            name="Grouped Actions Dog",
            slug="grouped-actions-dog",
            is_public=True,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("registry:dog-detail", args=[dog.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Contribute or request review")
        self.assertContains(response, 'class="profile-manage-actions ux-disclosure"', html=False)
        self.assertContains(response, "Request profile review")

    def test_dog_suggestions_return_live_matches(self):
        dog = Dog.objects.create(
            name="Suggestion Champion",
            slug="suggestion-champion",
            is_public=True,
            search_count=8,
        )
        DogImage.objects.create(dog=dog, image="dogs/suggestion.jpg", is_primary=True)

        response = self.client.get(
            reverse("registry:dog-suggestions"),
            {"q": "Suggestion"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["name"], "Suggestion Champion")

    def test_dog_suggestions_browse_returns_popular_sex_matches(self):
        sire = Dog.objects.create(
            name="Browse Sire",
            slug="browse-sire",
            sex=Dog.Sex.MALE,
            is_public=True,
            search_count=20,
        )
        dam = Dog.objects.create(
            name="Browse Dam",
            slug="browse-dam",
            sex=Dog.Sex.FEMALE,
            is_public=True,
            search_count=30,
        )
        DogImage.objects.create(dog=sire, image="dogs/browse-sire.jpg")
        DogImage.objects.create(dog=dam, image="dogs/browse-dam.jpg")

        response = self.client.get(
            reverse("registry:dog-suggestions"),
            {"browse": "1", "sex": "male"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["name"], "Browse Sire")

    def test_dog_suggestions_use_single_database_query(self):
        kennel = Kennel.objects.create(name="Fast Kennel", slug="fast-kennel")
        dog = Dog.objects.create(
            name="Performance Champion",
            slug="performance-champion",
            kennel=kennel,
            is_public=True,
            search_count=15,
        )
        DogRegistration.objects.create(dog=dog, number="PERF-001")
        DogImage.objects.create(dog=dog, image="dogs/performance.jpg")

        with self.assertNumQueries(1):
            response = self.client.get(
                reverse("registry:dog-suggestions"),
                {"q": "Performance"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["registration"], "PERF-001")

    def test_public_search_includes_published_image_less_match(self):
        dog = Dog.objects.create(
            name="Hidden Pedigree Record",
            slug="hidden-pedigree-record",
            is_public=True,
        )
        response = self.client.get(reverse("registry:dog-search"), {"q": "Hidden Pedigree"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, dog.name)
        self.assertContains(response, "Pedigree record · no public photo")

    def test_dog_suggestions_include_image_less_match(self):
        dog = Dog.objects.create(
            name="Hidden Suggestion Record",
            slug="hidden-suggestion-record",
            is_public=True,
        )
        response = self.client.get(
            reverse("registry:dog-suggestions"),
            {"q": "Hidden Suggestion"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            any(row["id"] == str(dog.pk) for row in response.json()["results"])
        )

    def test_private_dogs_remain_hidden_from_all_public_searches(self):
        Dog.objects.create(
            name="Private Member Dog", slug="private-member-dog", is_public=False,
        )
        results = self.client.get(
            reverse("registry:dog-search"), {"q": "Private Member Dog"}
        )
        suggestions = self.client.get(
            reverse("registry:dog-suggestions"), {"q": "Private Member Dog"}
        )
        self.assertEqual(results.context["result_count"], 0)
        self.assertEqual(suggestions.json()["results"], [])

    def test_public_profile_shows_additional_approved_photo_gallery(self):
        dog = Dog.objects.create(
            name="Gallery Champion", slug="gallery-champion", is_public=True,
        )
        DogImage.objects.create(
            dog=dog, image="dogs/portrait-original.jpg", is_primary=True
        )
        DogImage.objects.create(
            dog=dog, image="dogs/new-approved-photo.jpg", caption="Full body",
        )
        response = self.client.get(reverse("registry:dog-detail", args=[dog.slug]))
        self.assertContains(response, 'id="photos"', html=False)
        self.assertContains(response, "new-approved-photo.jpg")
        self.assertContains(response, "Full body")

    def test_public_dog_profile_always_exposes_coi(self):
        common = Dog.objects.create(
            name="COI Common", slug="coi-common-profile", is_public=True
        )
        sire = Dog.objects.create(
            name="COI Sire",
            slug="coi-sire-profile",
            sex=Dog.Sex.MALE,
            sire=common,
            is_public=True,
        )
        dam = Dog.objects.create(
            name="COI Dam",
            slug="coi-dam-profile",
            sex=Dog.Sex.FEMALE,
            sire=common,
            is_public=True,
        )
        dog = Dog.objects.create(
            name="COI Dog",
            slug="coi-dog-profile",
            sire=sire,
            dam=dam,
            is_public=True,
        )

        response = self.client.get(reverse("registry:dog-detail", args=[dog.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "COI")
        self.assertContains(response, "12.50%")

    def test_public_profile_hides_internal_source_attached_label(self):
        dog = Dog.objects.create(
            name="Public Verification Dog",
            slug="public-verification-dog",
            is_public=True,
            verification_state=VerificationState.SOURCE_ATTACHED,
        )
        HealthRecord.objects.create(
            dog=dog,
            test_type="Hips",
            result="Good",
            verification_state=VerificationState.SOURCE_ATTACHED,
        )

        response = self.client.get(reverse("registry:dog-detail", args=[dog.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Source attached")
        self.assertContains(response, "Not independently verified")

    def test_isolated_public_profile_requires_only_one_database_query(self):
        dog = Dog.objects.create(
            name="Isolated Dog", slug="isolated-dog", is_public=True
        )
        with self.assertNumQueries(1):
            response = self.client.get(reverse("registry:dog-detail", args=[dog.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["siblings"], [])
        self.assertEqual(response.context["offspring"], [])
        self.assertEqual(response.context["relative_health"], [])
        self.assertContains(response, "No health or DNA information has been published")

    def test_isolated_dog_with_health_keeps_record_and_skips_relation_query(self):
        dog = Dog.objects.create(
            name="Isolated Health Dog", slug="isolated-health-dog", is_public=True
        )
        HealthRecord.objects.create(dog=dog, test_type="Heart", result="Normal")
        with self.assertNumQueries(2):
            response = self.client.get(reverse("registry:dog-detail", args=[dog.slug]))
        self.assertEqual(response.context["siblings"], [])
        self.assertContains(response, "Normal")

    def test_dog_without_parents_still_displays_public_offspring(self):
        dog = Dog.objects.create(
            name="No Parent Sire", slug="no-parent-sire", is_public=True,
        )
        public_child = Dog.objects.create(
            name="Public Child", slug="public-child-no-parent", sire=dog, is_public=True
        )
        Dog.objects.create(
            name="Private Child", slug="private-child-no-parent", sire=dog, is_public=False
        )
        response = self.client.get(reverse("registry:dog-detail", args=[dog.slug]))
        self.assertEqual(
            [row.pk for row in response.context["offspring"]], [public_child.pk]
        )
        self.assertContains(response, "Public Child")
        self.assertNotContains(response, "Private Child")

    def test_empty_profile_extras_need_only_the_primary_lookup(self):
        dog = Dog.objects.create(
            name="Minimal Profile", slug="minimal-profile", is_public=True,
        )
        with self.assertNumQueries(1):
            profile = _public_profile_dog(dog.slug)
        self.assertEqual(profile.pk, dog.pk)
        self.assertEqual(profile.display_images, [])
        self.assertEqual(profile.display_registrations, [])
        self.assertEqual(profile.display_titles, [])
        self.assertEqual(profile.display_documents, [])
        self.assertEqual(profile.display_source_media, [])

    def test_complete_profile_fetches_every_published_section_without_extra_queries(self):
        dog = Dog.objects.create(
            name="Full Profile", slug="full-profile", is_public=True,
        )
        DogImage.objects.create(dog=dog, image="dogs/full-profile.jpg", is_primary=True)
        DogRegistration.objects.create(dog=dog, number="FULL-PROFILE-123")
        DogTitle.objects.create(dog=dog, name="Champion")
        DogDocument.objects.create(
            dog=dog, title="Public DNA", document_type=DogDocument.DocumentType.DNA,
            file="documents/public-dna.pdf", is_public=True,
        )
        DogDocument.objects.create(
            dog=dog, title="Private DNA", file="documents/private-dna.pdf",
            is_public=False,
        )
        with self.assertNumQueries(5):
            profile = _public_profile_dog(dog.slug)
        self.assertEqual(profile.display_images[0].image.name, "dogs/full-profile.jpg")
        self.assertEqual(profile.display_registrations[0].number, "FULL-PROFILE-123")
        self.assertEqual(profile.display_titles[0].name, "Champion")
        self.assertEqual([doc.title for doc in profile.display_documents], ["Public DNA"])
        self.assertEqual(profile.display_source_media, [])

    def test_unphotographed_profile_still_loads_trusted_source_image(self):
        dog = Dog.objects.create(
            name="Source Profile", slug="source-profile", is_public=True,
        )
        DogSource.objects.create(
            dog=dog,
            source_type=DogSource.SourceType.PEDIGREE,
            title="Public pedigree",
            raw_payload={
                "image_url": "https://canecorsopedigree.com/static/images/animal/source-profile.jpg"
            },
        )
        with self.assertNumQueries(2):
            profile = _public_profile_dog(dog.slug)
        self.assertEqual(profile.display_images, [])
        self.assertEqual(
            profile.source_image_url,
            "https://canecorsopedigree.com/static/images/animal/source-profile.jpg",
        )

    def test_profile_direct_relations_is_one_query_and_preserves_relationships(self):
        sire = Dog.objects.create(name="Common Sire", slug="common-sire", is_public=True)
        dam = Dog.objects.create(name="Common Dam", slug="common-dam", is_public=True)
        dog = Dog.objects.create(
            name="Profile Subject", slug="profile-subject", sire=sire, dam=dam, is_public=True
        )
        full = Dog.objects.create(
            name="A Full Sibling", slug="a-full-sibling", sire=sire, dam=dam, is_public=True
        )
        half = Dog.objects.create(
            name="B Half Sibling", slug="b-half-sibling", sire=sire, is_public=True
        )
        child = Dog.objects.create(
            name="C Offspring", slug="c-offspring", sire=dog, is_public=True
        )
        with self.assertNumQueries(1):
            siblings, offspring = profile_direct_relations(dog, limit=5)
        self.assertEqual(
            [(row["dog"].pk, row["relation"], row["shared_parents"]) for row in siblings],
            [(full.pk, "Full sibling", ("sire", "dam")),
             (half.pk, "Half sibling", ("sire",))],
        )
        self.assertEqual([row.pk for row in offspring], [child.pk])

    def test_profile_direct_relations_bounds_each_category_and_excludes_private(self):
        sire = Dog.objects.create(name="Preview Parent", slug="preview-parent", is_public=True)
        subject = Dog.objects.create(
            name="Preview Subject", slug="preview-subject", sire=sire, is_public=True
        )
        for index in range(6):
            Dog.objects.create(
                name=f"Sibling {index}", slug=f"relation-sibling-{index}",
                sire=sire, is_public=True,
            )
            Dog.objects.create(
                name=f"Child {index}", slug=f"relation-child-{index}",
                sire=subject, is_public=True,
            )
        Dog.objects.create(
            name="A Private Sibling", slug="private-sibling", sire=sire, is_public=False
        )
        Dog.objects.create(
            name="A Private Child", slug="private-child", sire=subject, is_public=False
        )
        with self.assertNumQueries(1):
            siblings, offspring = profile_direct_relations(subject, limit=3)
        self.assertEqual([row["dog"].name for row in siblings], [
            "Sibling 0", "Sibling 1", "Sibling 2",
        ])
        self.assertEqual([row.name for row in offspring], [
            "Child 0", "Child 1", "Child 2",
        ])

    def test_profile_direct_relations_keeps_dog_in_both_relationship_buckets(self):
        common_dam = Dog.objects.create(
            name="Double Relation Dam", slug="double-relation-dam", is_public=True
        )
        subject = Dog.objects.create(
            name="Double Relation Subject", slug="double-relation-subject",
            dam=common_dam, is_public=True,
        )
        both = Dog.objects.create(
            name="Double Relation Child", slug="double-relation-child",
            sire=subject, dam=common_dam, is_public=True,
        )
        with self.assertNumQueries(1):
            siblings, offspring = profile_direct_relations(subject, limit=1)
        self.assertEqual([row["dog"].pk for row in siblings], [both.pk])
        self.assertEqual(siblings[0]["relation"], "Half sibling")
        self.assertEqual([row.pk for row in offspring], [both.pk])

    def test_public_dog_profile_bounds_large_relationship_previews(self):
        sire = Dog.objects.create(
            name="Preview Sire",
            slug="preview-sire",
            sex=Dog.Sex.MALE,
            is_public=True,
        )
        dog = Dog.objects.create(
            name="Preview Dog",
            slug="preview-dog",
            sire=sire,
            sex=Dog.Sex.MALE,
            is_public=True,
        )
        for index in range(3):
            Dog.objects.create(
                name=f"Preview Sibling {index}",
                slug=f"preview-sibling-{index}",
                sire=sire,
                is_public=True,
            )
            dam = Dog.objects.create(
                name=f"Preview Dam {index}",
                slug=f"preview-dam-{index}",
                sex=Dog.Sex.FEMALE,
                is_public=True,
            )
            Dog.objects.create(
                name=f"Preview Child {index}",
                slug=f"preview-child-{index}",
                sire=dog,
                dam=dam,
                is_public=True,
            )

        with patch("registry.views.PROFILE_RELATION_PREVIEW_LIMIT", 2):
            response = self.client.get(reverse("registry:dog-detail", args=[dog.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["siblings"]), 2)
        self.assertEqual(len(response.context["offspring"]), 2)
        self.assertEqual(len(response.context["mates"]), 2)
        self.assertTrue(response.context["siblings_truncated"])
        self.assertTrue(response.context["offspring_truncated"])
        self.assertTrue(response.context["mates_truncated"])

    def test_public_search_finds_external_registration_number(self):
        dog = Dog.objects.create(name="Branco", slug="branco", is_public=True)
        DogImage.objects.create(dog=dog, image="dogs/branco.jpg")
        authority = RegistrationAuthority.objects.create(code="KSS", name="Kennel authority")
        DogRegistration.objects.create(dog=dog, authority=authority, number="JR 710606 Cc")

        response = self.client.get(reverse("registry:dog-search"), {"q": "710606"})

        self.assertContains(response, "Branco")

    def test_kennel_directory_searches_name_city_and_country(self):
        Kennel.objects.create(name="Sforza", slug="sforza", city="Rome", country="Italy")
        Kennel.objects.create(name="Custodi Nos", slug="custodi-nos", country="Serbia")

        response = self.client.get(reverse("registry:kennel-list"), {"q": "Rome"})

        self.assertContains(response, "Sforza")
        self.assertNotContains(response, "Custodi Nos")

    def test_kennel_directory_is_bounded_to_eighteen_names_per_page(self):
        for index in range(25):
            Kennel.objects.create(name=f"Kennel {index:02d}", slug=f"kennel-{index:02d}")

        response = self.client.get(reverse("registry:kennel-list"))

        self.assertEqual(len(response.context["kennels"]), 18)
        self.assertTrue(response.context["page_obj"].has_next())

    def test_kennel_gallery_only_uses_photographed_dog_cards(self):
        kennel = Kennel.objects.create(name="Photo Kennel", slug="photo-kennel")
        photographed = Dog.objects.create(
            name="Photographed Dog",
            slug="photographed-dog",
            kennel=kennel,
            is_public=True,
        )
        source_backed = Dog.objects.create(
            name="Source Photo Dog",
            slug="source-photo-dog",
            kennel=kennel,
            is_public=True,
        )
        Dog.objects.create(
            name="Pedigree Only Dog",
            slug="pedigree-only-dog",
            kennel=kennel,
            is_public=True,
        )
        DogImage.objects.create(
            dog=photographed,
            image="dogs/photo-kennel/photographed.jpg",
            is_primary=True,
        )
        DogSource.objects.create(
            dog=source_backed,
            source_type=DogSource.SourceType.REGISTRY,
            title="Source photo",
            source_url="https://www.canecorsopedigree.com/dog/source-photo-dog",
            raw_payload={
                "image_url": "https://www.canecorsopedigree.com/static/images/animal/source-photo.jpg"
            },
        )

        response = self.client.get(reverse("registry:kennel-detail", args=[kennel.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["dog_total"], 2)
        self.assertEqual(response.context["public_dog_total"], 3)
        self.assertContains(response, "Dogs with photos")
        self.assertContains(response, "Photographed Dog")
        self.assertContains(response, "Source Photo Dog")
        self.assertNotContains(response, "Pedigree Only Dog")

    def test_litter_keeps_image_less_offspring_as_linked_text_records(self):
        sire = Dog.objects.create(
            name="Gallery Sire",
            slug="gallery-sire",
            sex=Dog.Sex.MALE,
            is_public=True,
        )
        dam = Dog.objects.create(
            name="Gallery Dam",
            slug="gallery-dam",
            sex=Dog.Sex.FEMALE,
            is_public=True,
        )
        litter = Litter.objects.create(
            code="GALLERY-LITTER",
            sire=sire,
            dam=dam,
            date_of_birth="2026-10-07",
            is_public=True,
        )
        photographed = Dog.objects.create(
            name="Photo Puppy",
            slug="photo-puppy",
            litter=litter,
            sire=sire,
            dam=dam,
            date_of_birth="2026-10-07",
            is_public=True,
        )
        DogImage.objects.create(
            dog=photographed,
            image="dogs/gallery/photo-puppy.jpg",
            is_primary=True,
        )
        Dog.objects.create(
            name="No Photo Puppy",
            slug="no-photo-puppy",
            litter=litter,
            sire=sire,
            dam=dam,
            date_of_birth="2026-10-07",
            is_public=True,
        )

        response = self.client.get(reverse("registry:litter-detail", args=[litter.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["offspring_total"], 2)
        self.assertEqual(len(response.context["imaged_offspring"]), 1)
        self.assertEqual(len(response.context["other_offspring"]), 1)
        self.assertContains(response, "Photo Puppy")
        self.assertContains(response, "No Photo Puppy")
        self.assertContains(response, "Other registered offspring")
        self.assertNotContains(response, '<div class="media-placeholder">CCA</div>', html=False)

    def test_explicit_search_includes_public_image_less_record(self):
        Dog.objects.create(
            name="Text Only Champion",
            slug="text-only-champion",
            is_public=True,
        )

        response = self.client.get(
            reverse("registry:dog-search"),
            {"q": "Text Only Champion"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["result_count"], 1)
        self.assertEqual([dog.name for dog in response.context["dogs"]], ["Text Only Champion"])

    def test_generated_litter_uses_parent_pair_as_public_label(self):
        sire = Dog.objects.create(name="Atlas", slug="atlas-litter-label", sex=Dog.Sex.MALE)
        dam = Dog.objects.create(name="Hera", slug="hera-litter-label", sex=Dog.Sex.FEMALE)
        litter = Litter.objects.create(
            code="AUTO-20261007-1234567890abcdef",
            sire=sire,
            dam=dam,
            date_of_birth="2026-10-07",
            is_public=True,
        )

        self.assertEqual(litter.public_label, "Atlas × Hera")

    def test_manual_litter_code_remains_public_label(self):
        litter = Litter.objects.create(code="BELLISSIMO-A-2026", is_public=True)

        self.assertEqual(litter.public_label, "BELLISSIMO-A-2026")

    def test_public_kennel_and_litter_pages_hide_generated_internal_code(self):
        kennel = Kennel.objects.create(name="Label Kennel", slug="label-kennel")
        sire = Dog.objects.create(name="Label Sire", slug="label-sire", sex=Dog.Sex.MALE, is_public=True)
        dam = Dog.objects.create(name="Label Dam", slug="label-dam", sex=Dog.Sex.FEMALE, is_public=True)
        litter = Litter.objects.create(
            code="AUTO-20261007-feedfacefeedface",
            kennel=kennel,
            sire=sire,
            dam=dam,
            date_of_birth="2026-10-07",
            is_public=True,
        )

        kennel_response = self.client.get(reverse("registry:kennel-detail", args=[kennel.slug]))
        litter_response = self.client.get(reverse("registry:litter-detail", args=[litter.pk]))

        self.assertContains(kennel_response, "Label Sire × Label Dam")
        self.assertNotContains(kennel_response, "AUTO-20261007")
        self.assertContains(litter_response, "Label Sire × Label Dam")
        self.assertNotContains(litter_response, "AUTO-20261007")

    def test_dog_profile_collapses_secondary_relationships_after_six(self):
        sire = Dog.objects.create(
            name="Disclosure Sire",
            slug="disclosure-sire",
            sex=Dog.Sex.MALE,
            is_public=True,
        )
        dog = Dog.objects.create(
            name="Disclosure Dog",
            slug="disclosure-dog",
            sire=sire,
            is_public=True,
        )
        for index in range(7):
            Dog.objects.create(
                name=f"Disclosure Sibling {index}",
                slug=f"disclosure-sibling-{index}",
                sire=sire,
                is_public=True,
            )

        response = self.client.get(reverse("registry:dog-detail", args=[dog.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Show 1 more sibling")
        self.assertContains(response, 'class="relationship-more"', html=False)

