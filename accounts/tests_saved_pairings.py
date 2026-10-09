"""Saved mating comparisons are private research, never breeding records."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import SavedPairing
from registry.models import Dog, ModerationRoleAssignment
from registry.services import merge_dogs


class SavedPairingTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.member = User.objects.create_user(username="research-member")
        self.other_member = User.objects.create_user(username="other-research-member")
        self.staff = User.objects.create_user(username="research-moderator")
        ModerationRoleAssignment.objects.create(
            user=self.staff, role=ModerationRoleAssignment.Role.REVIEWER,
        )
        self.sire = Dog.objects.create(
            name="Research Sire", slug="research-sire",
            sex=Dog.Sex.MALE, is_public=True,
        )
        self.dam = Dog.objects.create(
            name="Research Dam", slug="research-dam",
            sex=Dog.Sex.FEMALE, is_public=True,
        )

    def save(self, **overrides):
        data = {
            "sire": str(self.sire.pk), "dam": str(self.dam.pk),
            "label": "Summer research", "notes": "Compare lineage",
        }
        data.update(overrides)
        return self.client.post(reverse("accounts:save-pairing"), data)

    def test_member_can_save_idempotently_and_reanalyse(self):
        self.client.force_login(self.member)
        self.assertEqual(self.save().status_code, 302)
        self.assertEqual(self.save().status_code, 302)
        self.assertEqual(SavedPairing.objects.filter(member=self.member).count(), 1)
        page = self.client.get(reverse("accounts:saved-pairings"))
        self.assertContains(page, "Research Sire")
        self.assertContains(page, "Research Dam")
        self.assertContains(page, "Summer research")
        self.assertContains(page, "Compare lineage")
        self.assertContains(page, "generations=8")
        analysis = self.client.get(reverse("pedigrees:virtual-mating"), {
            "sire": str(self.sire.pk), "dam": str(self.dam.pk),
        })
        self.assertEqual(analysis.status_code, 200)
        self.assertContains(analysis, "Save to My research")

    def test_member_cannot_delete_other_members_private_pairing(self):
        pairing = SavedPairing.objects.create(
            member=self.member, sire=self.sire, dam=self.dam,
        )
        self.client.force_login(self.other_member)
        list_page = self.client.get(reverse("accounts:saved-pairings"))
        self.assertNotContains(list_page, "Research Sire")
        result = self.client.post(reverse(
            "accounts:delete-saved-pairing", args=[pairing.pk],
        ))
        self.assertEqual(result.status_code, 404)
        self.assertTrue(SavedPairing.objects.filter(pk=pairing.pk).exists())
        self.client.force_login(self.member)
        self.assertEqual(self.client.post(reverse(
            "accounts:delete-saved-pairing", args=[pairing.pk],
        )).status_code, 302)
        self.assertFalse(SavedPairing.objects.filter(pk=pairing.pk).exists())

    def test_staff_cannot_save_or_read_member_research(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("accounts:saved-pairings")).status_code, 403)
        self.assertEqual(self.save().status_code, 403)
        self.assertFalse(SavedPairing.objects.exists())

    def test_private_or_mismatched_dogs_cannot_be_saved(self):
        private = Dog.objects.create(
            name="Private Dam", slug="private-research-dam", sex=Dog.Sex.FEMALE,
        )
        self.client.force_login(self.member)
        self.assertEqual(self.save(dam=str(private.pk)).status_code, 302)
        self.assertEqual(self.save(dam=str(self.sire.pk)).status_code, 302)
        self.assertFalse(SavedPairing.objects.exists())

    def test_merge_keeps_bookmarks_and_consolidates_duplicate_pairs(self):
        duplicate = Dog.objects.create(
            name="Duplicate Sire", slug="duplicate-research-sire",
            sex=Dog.Sex.MALE, is_public=True,
        )
        a = SavedPairing.objects.create(
            member=self.member, sire=self.sire, dam=self.dam,
            notes="Original note",
        )
        b = SavedPairing.objects.create(
            member=self.member, sire=duplicate, dam=self.dam,
            notes="Additional note",
        )
        history = merge_dogs(self.sire, duplicate)
        a.refresh_from_db()
        self.assertFalse(SavedPairing.objects.filter(pk=b.pk).exists())
        self.assertEqual(a.sire_id, self.sire.pk)
        self.assertIn("Original note", a.notes)
        self.assertIn("Additional note", a.notes)
        self.assertEqual(history.summary["saved_pairings_combined"], 1)
        self.assertEqual(SavedPairing.objects.filter(member=self.member).count(), 1)

    def test_self_pairing_after_merge_stays_private_and_needs_review(self):
        duplicate = Dog.objects.create(
            name="Duplicate Sire Two", slug="duplicate-sire-two",
            sex=Dog.Sex.MALE, is_public=True,
        )
        pairing = SavedPairing.objects.create(
            member=self.member, sire=self.sire, dam=duplicate,
            notes="Keep research",
        )
        merge_dogs(self.sire, duplicate)
        pairing.refresh_from_db()
        self.assertEqual(pairing.sire_id, self.sire.pk)
        self.assertIsNone(pairing.dam_id)
        self.assertEqual(pairing.notes, "Keep research")
        self.client.force_login(self.member)
        self.assertContains(self.client.get(reverse("accounts:saved-pairings")), "needs a published parent")


    def compare_url(self, *pairings, depth=8):
        from django.http import QueryDict
        params = QueryDict(mutable=True)
        params.setlist("pairing", [str(pairing.pk) for pairing in pairings])
        params["generations"] = str(depth)
        return reverse("accounts:compare-saved-pairings") + "?" + params.urlencode()

    def test_two_saved_pairings_have_private_side_by_side_metrics(self):
        other_sire = Dog.objects.create(
            name="Second Research Sire", slug="second-research-sire",
            sex=Dog.Sex.MALE, is_public=True,
        )
        first = SavedPairing.objects.create(
            member=self.member, sire=self.sire, dam=self.dam,
            label="First comparison",
        )
        second = SavedPairing.objects.create(
            member=self.member, sire=other_sire, dam=self.dam,
            label="Second comparison",
        )
        self.client.force_login(self.member)
        listing = self.client.get(reverse("accounts:saved-pairings"))
        self.assertContains(listing, "Compare 2–3 selected pairings")
        self.assertContains(listing, 'form="saved-compare-form"', count=2)
        original_dog_count = Dog.objects.count()
        original_pairing_count = SavedPairing.objects.count()
        response = self.client.get(self.compare_url(first, second))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "First comparison")
        self.assertContains(response, "Second comparison")
        self.assertContains(response, "Projected offspring COI")
        self.assertContains(response, "Pedigree coverage")
        self.assertContains(response, "not a breeding recommendation")
        self.assertContains(response, "Full analysis")
        self.assertEqual(len(response.context["comparisons"]), 2)
        self.assertEqual(response.context["generations"], 8)
        self.assertEqual(response.context["comparisons"][0]["pairing"], first)
        self.assertEqual(
            response.context["comparisons"][0]["analysis"]["total_slots"], 510
        )
        self.assertEqual(Dog.objects.count(), original_dog_count)
        self.assertEqual(SavedPairing.objects.count(), original_pairing_count)

    def test_comparison_is_member_private_and_rejects_unowned_identifiers(self):
        first = SavedPairing.objects.create(
            member=self.member, sire=self.sire, dam=self.dam,
        )
        private_sire = Dog.objects.create(
            name="Other Member Sire", slug="other-member-sire",
            sex=Dog.Sex.MALE, is_public=True,
        )
        secret = SavedPairing.objects.create(
            member=self.other_member, sire=private_sire, dam=self.dam,
            notes="Private kennel plan nobody else can read",
        )
        self.client.force_login(self.member)
        response = self.client.get(self.compare_url(first, secret))
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("Private kennel plan", response.content.decode())
        self.client.force_login(self.other_member)
        self.assertEqual(self.client.get(self.compare_url(first, secret)).status_code, 404)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(self.compare_url(first, secret)).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.compare_url(first, secret)).status_code, 302)

    def test_comparison_rejects_bad_or_unbounded_selections(self):
        first = SavedPairing.objects.create(
            member=self.member, sire=self.sire, dam=self.dam,
        )
        self.client.force_login(self.member)
        base = reverse("accounts:compare-saved-pairings")
        self.assertEqual(self.client.get(base).status_code, 400)
        self.assertEqual(self.client.get(self.compare_url(first)).status_code, 400)
        self.assertEqual(self.client.get(self.compare_url(first, first)).status_code, 400)
        self.assertEqual(self.client.get(base, {
            "pairing": ["not-a-uuid", str(first.pk)]
        }).status_code, 400)
        self.assertEqual(self.client.get(self.compare_url(first, first, depth=999)).status_code, 400)
        self.assertEqual(self.client.get(base, {
            "pairing": [str(first.pk)] * 4
        }).status_code, 400)

    def test_comparison_handles_unpublished_parent_without_leak_or_mutation(self):
        other_sire = Dog.objects.create(
            name="Temporarily Hidden Sire", slug="temporarily-hidden-sire",
            sex=Dog.Sex.MALE, is_public=True,
        )
        first = SavedPairing.objects.create(
            member=self.member, sire=self.sire, dam=self.dam,
        )
        second = SavedPairing.objects.create(
            member=self.member, sire=other_sire, dam=self.dam,
        )
        Dog.objects.filter(pk=other_sire.pk).update(is_public=False)
        self.client.force_login(self.member)
        response = self.client.get(self.compare_url(first, second))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "no longer published")
        self.assertNotContains(response, "Temporarily Hidden Sire")
        self.assertEqual(len(response.context["comparisons"]), 2)
        self.assertIsNone(response.context["comparisons"][1]["analysis"])
        other_sire.refresh_from_db()
        self.assertFalse(other_sire.is_public)

    def test_comparison_updates_after_pedigree_improvement(self):
        second_sire = Dog.objects.create(
            name="Linked Research Sire", slug="linked-research-sire",
            sex=Dog.Sex.MALE, is_public=True,
        )
        ancestor = Dog.objects.create(
            name="Older Research Ancestor", slug="older-research-ancestor",
            sex=Dog.Sex.MALE, is_public=True,
        )
        first = SavedPairing.objects.create(
            member=self.member, sire=self.sire, dam=self.dam,
        )
        second = SavedPairing.objects.create(
            member=self.member, sire=second_sire, dam=self.dam,
        )
        self.client.force_login(self.member)
        url = self.compare_url(first, second, depth=4)
        before = self.client.get(url).context["comparisons"][1]["analysis"]["known_slots"]
        second_sire.sire = ancestor
        second_sire.save()
        after = self.client.get(url).context["comparisons"][1]["analysis"]["known_slots"]
        self.assertGreater(after, before)
