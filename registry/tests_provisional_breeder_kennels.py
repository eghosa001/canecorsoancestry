"""High-signal archived kennel name links never create dogs or claim verified breeders."""
import json
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse

from registry.management.commands.link_provisional_archive_kennels import CONFIRM
from registry.models import Dog, DogExternalKey, Kennel, ModerationAudit


class ProvisionalKennelLinkTests(TestCase):
    def setUp(self):
        self.dog = Dog.objects.create(
            name="SCANDIFIO'S SOPHIE ROSE",
            slug="scandifio-sophie-rose-research",
            is_public=True,
        )
        DogExternalKey.objects.create(
            dog=self.dog, namespace="canecorsopedigree.com", key="70472",
        )
        self.initial_dog_count = Dog.objects.count()

    def run_plan(self, **args):
        out = StringIO()
        call_command("link_provisional_archive_kennels", stdout=out, **args)
        report = next(
            s.partition("=")[2] for s in out.getvalue().splitlines()
            if s.startswith("PROVISIONAL_BREEDER_KENNEL_LINK_PLAN=")
        )
        return json.loads(report), out.getvalue()

    def test_dry_run_does_not_add_kennels_dogs_or_owners(self):
        plan, output = self.run_plan()
        self.assertEqual(plan["existing_dogs_with_new_research_links"], 1)
        self.assertEqual(plan["new_unverified_kennel_profiles"], 1)
        self.assertEqual(plan["canonical_breeding_kennels_changed"], 0)
        self.assertIn("DRY RUN ONLY", output)
        self.assertEqual(Kennel.objects.count(), 0)
        self.assertEqual(Dog.objects.count(), self.initial_dog_count)
        self.dog.refresh_from_db()
        self.assertIsNone(self.dog.kennel_id)
        self.assertIsNone(self.dog.inferred_kennel_id)
        self.assertFalse(ModerationAudit.objects.exists())

    def test_requires_exact_reviewed_counts_and_backup_before_any_apply(self):
        with self.assertRaisesRegex(CommandError, "backup verification"):
            self.run_plan(apply=True, expected_links=1, expected_new_kennels=1)
        with self.assertRaisesRegex(CommandError, "counts changed"):
            self.run_plan(
                apply=True, expected_links=100, expected_new_kennels=1,
                backup_confirmation=CONFIRM,
            )
        self.assertFalse(Kennel.objects.exists())

    def test_creates_unverified_kennel_and_connects_only_existing_dog(self):
        plan, result = self.run_plan(
            apply=True, expected_links=1, expected_new_kennels=1,
            backup_confirmation=CONFIRM,
        )
        self.assertEqual(plan["existing_dogs_with_new_research_links"], 1)
        self.assertIn("new dogs: 0", result)
        self.assertEqual(Dog.objects.count(), self.initial_dog_count)
        kennel = Kennel.objects.get()
        self.assertEqual(kennel.name.upper(), "SCANDIFIO'S")
        self.assertTrue(kennel.is_archive_hypothesis)
        self.assertIsNone(kennel.verified_at)
        self.assertFalse(kennel.memberships.exists())
        self.dog.refresh_from_db()
        self.assertIsNone(self.dog.kennel_id)
        self.assertEqual(self.dog.inferred_kennel_id, kennel.pk)
        self.assertEqual(
            self.dog.inferred_kennel_evidence["verification"],
            "unverified_research_hypothesis",
        )
        self.assertTrue(ModerationAudit.objects.filter(
            summary__kind="unverified_archive_breeder_name_link"
        ).exists())
        profile = self.client.get(reverse("registry:dog-detail", args=[self.dog.slug]))
        self.assertEqual(profile.status_code, 200)
        self.assertContains(profile, "Possible breeding kennel (unverified)")
        self.assertContains(profile, kennel.name)
        self.assertContains(profile, reverse("registry:kennel-detail", args=[kennel.slug]))
        kennel_profile = self.client.get(
            reverse("registry:kennel-detail", args=[kennel.slug])
        )
        self.assertEqual(kennel_profile.status_code, 200)
        self.assertContains(kennel_profile, "Possible kennel-origin matches")
        self.assertContains(kennel_profile, "No confirmed breeding-origin links yet.")
        self.assertNotContains(kennel_profile, "No public dogs are linked yet.")
        self.assertContains(kennel_profile, "SCANDIFIO&#x27;S SOPHIE ROSE")
        directory = self.client.get(reverse("registry:kennel-list"))
        self.assertContains(directory, "Historical name")
        self.assertContains(directory, "possible origin match (unverified)")
        self.assertNotContains(directory, "possible origin matchs")
        self.assertEqual(directory.context["kennels"][0].public_dog_count, 0)
        self.assertEqual(directory.context["kennels"][0].possible_breeding_dog_count, 1)
        second, _ = self.run_plan()
        self.assertEqual(second["existing_dogs_with_new_research_links"], 0)

    def test_confirmed_canonical_kennel_always_overrides_research_link(self):
        self.run_plan(
            apply=True, expected_links=1, expected_new_kennels=1,
            backup_confirmation=CONFIRM,
        )
        confirmed = Kennel.objects.create(name="Another real breeder", slug="real-breeder")
        self.dog.kennel = confirmed
        self.dog.save(update_fields=["kennel"])
        response = self.client.get(reverse("registry:dog-detail", args=[self.dog.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Breeding kennel")
        self.assertContains(response, "Another real breeder")
        self.assertNotContains(response, "Possible breeding kennel (unverified)")

    def test_name_only_without_original_archive_key_is_not_assigned(self):
        DogExternalKey.objects.filter(dog=self.dog).delete()
        plan, _ = self.run_plan()
        self.assertEqual(plan["existing_dogs_with_new_research_links"], 0)

    def test_ambiguous_two_kennel_phrases_are_skipped(self):
        self.dog.name = "SCANDIFIO'S ISOTTA DELL'APPIO"
        self.dog.save(update_fields=["name"])
        plan, _ = self.run_plan()
        self.assertEqual(plan["existing_dogs_with_new_research_links"], 0)
        self.assertGreaterEqual(
            plan["skipped_unverified_or_ambiguous"].get(
                "ambiguous_name_affixes", 0
            ), 1
        )
