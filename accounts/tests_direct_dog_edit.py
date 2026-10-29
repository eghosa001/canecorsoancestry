"""Focused authorization, transaction, revision, and review coverage."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from registry.models import Dog, DogTitle, Kennel, ModerationAudit, ModerationRoleAssignment


class DirectDogEditTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_superuser(
            username="direct-owner", email="direct-owner@example.com", password="passwordA123!"
        )
        self.moderator = User.objects.create_user(
            username="direct-moderator", email="direct-moderator@example.com", password="passwordB123!"
        )
        self.member = User.objects.create_user(
            username="direct-member", email="direct-member@example.com", password="passwordC123!"
        )
        ModerationRoleAssignment.objects.create(
            user=self.owner, role=ModerationRoleAssignment.Role.OWNER, assigned_by=self.owner
        )
        ModerationRoleAssignment.objects.create(
            user=self.moderator, role=ModerationRoleAssignment.Role.REVIEWER, assigned_by=self.owner
        )
        self.dog = Dog.objects.create(
            name="Original Dog", slug="direct-original-dog", sex=Dog.Sex.MALE, is_public=True
        )

    def editor(self):
        return reverse("accounts:dog-direct-edit", args=(self.dog.pk,))

    def revision_url(self, audit):
        return reverse("accounts:dog-review-edit", args=(self.dog.pk, audit.pk))

    def submission(self, **updates):
        response = self.client.get(self.editor())
        self.assertEqual(response.status_code, 200)
        payload = {
            "version": response.context["version"],
            "name": self.dog.name,
            "sex": self.dog.sex,
            "verification_state": self.dog.verification_state,
            "reason": "Corrected against the documented dog record",
        }
        for name, formset in response.context["formsets"].items():
            for field, value in formset.management_form.initial.items():
                payload[f"{name}-{field}"] = str(value)
            for index, form in enumerate(formset.forms):
                for field_name in form.fields:
                    if field_name in {"DELETE", "dog"}:
                        continue
                    # The browser submits default select/number values even
                    # for untouched extra forms. Mirror that behavior.
                    value = form[field_name].value()
                    if value is None or value is False:
                        continue
                    if hasattr(value, "name") and hasattr(value, "storage"):
                        continue
                    if value is True:
                        value = "on"
                    payload[f"{name}-{index}-{field_name}"] = str(value)
        payload.update(updates)
        return payload

    def test_staff_can_find_a_dog_and_preview_kennel_association_without_saving(self):
        kennel = Kennel.objects.create(name="Pet Palace", slug="pet-palace")
        self.client.force_login(self.moderator)
        kennel_page = self.client.get(
            reverse("accounts:kennel-publication-detail", args=[kennel.pk])
        )
        self.assertEqual(kennel_page.status_code, 200)
        self.assertContains(kennel_page, "Find existing dog to associate")
        finder = self.client.get(
            reverse("accounts:dog-edit-list"),
            {"kennel": str(kennel.pk), "q": "Original Dog"},
        )
        self.assertEqual(finder.status_code, 200)
        self.assertContains(finder, "Review kennel association")
        editor = self.client.get(
            self.editor(), {"kennel": str(kennel.pk)}
        )
        self.assertEqual(editor.status_code, 200)
        self.assertEqual(editor.context["form"]["kennel_ref"].value(), str(kennel.pk))
        self.dog.refresh_from_db()
        self.assertIsNone(self.dog.kennel_id)

    def test_moderator_kennel_association_requires_owner_review(self):
        kennel = Kennel.objects.create(name="Pet Palace", slug="pet-palace")
        self.client.force_login(self.moderator)
        response = self.client.post(
            self.editor(), self.submission(kennel_ref=str(kennel.pk))
        )
        self.assertEqual(response.status_code, 302)
        self.dog.refresh_from_db()
        self.assertIsNone(self.dog.kennel_id)
        proposal = ModerationAudit.objects.get(summary__kind="direct_dog_proposal")
        self.assertEqual(proposal.summary["proposed_changes"]["kennel"], str(kennel.pk))
        self.client.force_login(self.owner)
        response = self.client.post(
            self.revision_url(proposal),
            {"decision": "approve", "reason": "Verified official kennel ownership documents"},
        )
        self.assertEqual(response.status_code, 302)
        self.dog.refresh_from_db()
        self.assertEqual(self.dog.kennel_id, kennel.pk)
        self.assertTrue(self.dog.is_public)

    def test_moderator_changes_live_with_before_after_audit(self):
        self.client.force_login(self.moderator)
        response = self.client.post(
            self.editor(), self.submission(name="Corrected Dog", country="Italy")
        )
        self.assertEqual(response.status_code, 302)
        self.dog.refresh_from_db()
        self.assertEqual(self.dog.name, "Corrected Dog")
        self.assertEqual(self.dog.country, "Italy")
        self.assertEqual(self.dog.slug, "direct-original-dog")  # keep existing links
        audit = ModerationAudit.objects.get(summary__kind="direct_dog_edit")
        self.assertEqual(audit.actor, self.moderator)
        self.assertEqual(audit.summary["before"]["dog"]["name"], "Original Dog")
        self.assertEqual(audit.summary["after"]["dog"]["name"], "Corrected Dog")

    def test_super_admin_can_revert_a_moderator_edit_and_new_related_title(self):
        self.client.force_login(self.moderator)
        self.client.post(
            self.editor(), self.submission(name="Mistaken Name", **{"titles-TOTAL_FORMS": "1", "titles-0-name": "Wrong title"})
        )
        self.dog.refresh_from_db()
        self.assertEqual(self.dog.name, "Mistaken Name")
        self.assertTrue(DogTitle.objects.filter(dog=self.dog, name="Wrong title").exists())
        audit = ModerationAudit.objects.get(summary__kind="direct_dog_edit")
        self.client.force_login(self.owner)
        response = self.client.post(
            self.revision_url(audit), {"decision": "revert", "reason": "The source shows the original name"}
        )
        self.assertEqual(response.status_code, 302)
        self.dog.refresh_from_db()
        self.assertEqual(self.dog.name, "Original Dog")
        self.assertFalse(DogTitle.objects.filter(dog=self.dog, name="Wrong title").exists())
        self.assertTrue(ModerationAudit.objects.filter(
            summary__kind="direct_dog_revert",
            summary__original_audit_id=str(audit.pk),
        ).exists())

    def test_super_admin_can_accept_and_not_review_twice(self):
        self.client.force_login(self.moderator)
        self.client.post(self.editor(), self.submission(colour="Grey"))
        audit = ModerationAudit.objects.get(summary__kind="direct_dog_edit")
        self.client.force_login(self.owner)
        for _ in range(2):
            self.client.post(self.revision_url(audit), {
                "decision": "accept", "reason": "Checked against pedigree documentation",
            })
        self.assertEqual(ModerationAudit.objects.filter(
            summary__kind="direct_dog_review",
            summary__original_audit_id=str(audit.pk),
        ).count(), 1)

    def test_member_cannot_access_editor_or_review(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(reverse("accounts:dog-edit-list")).status_code, 403)
        self.assertEqual(self.client.get(self.editor()).status_code, 403)
        self.assertEqual(self.client.post(self.editor(), {}).status_code, 403)

    def test_moderator_cannot_review_and_cannot_edit_locked_record(self):
        self.client.force_login(self.moderator)
        self.dog.is_record_locked = True
        self.dog.record_locked_by = self.owner
        self.dog.save()
        self.assertEqual(self.client.get(self.editor()).status_code, 403)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.editor()).status_code, 200)

    def test_stale_version_is_rejected(self):
        self.client.force_login(self.moderator)
        original_payload = self.submission(name="Out of date name")
        Dog.objects.filter(pk=self.dog.pk).update(name="Updated by another editor")
        self.dog.refresh_from_db()
        self.dog.save()  # bump updated_at before submitting the stale form
        response = self.client.post(self.editor(), original_payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "dog changed while this form was open")
        self.dog.refresh_from_db()
        self.assertEqual(self.dog.name, "Updated by another editor")
        self.assertFalse(ModerationAudit.objects.filter(summary__kind="direct_dog_edit").exists())

    def test_old_audit_cannot_overwrite_a_later_change(self):
        self.client.force_login(self.moderator)
        self.client.post(self.editor(), self.submission(name="Name after first edit"))
        first = ModerationAudit.objects.get(summary__kind="direct_dog_edit")
        self.dog.refresh_from_db()
        self.client.post(self.editor(), self.submission(colour="Brown"))
        self.client.force_login(self.owner)
        response = self.client.post(self.revision_url(first), {
            "decision": "revert", "reason": "Undo the first edit without losing later edits",
        })
        self.assertEqual(response.status_code, 302)
        self.dog.refresh_from_db()
        self.assertEqual(self.dog.name, "Name after first edit")
        self.assertEqual(self.dog.colour, "Brown")
        self.assertFalse(ModerationAudit.objects.filter(
            summary__kind="direct_dog_revert",
            summary__original_audit_id=str(first.pk),
        ).exists())

    def test_full_dog_search_ignores_queue_and_finds_middle_name_and_private_dogs(self):
        from registry.models import DogRegistration
        exact = Dog.objects.create(name="ZEUS", slug="search-zeus-exact", is_public=True)
        internal = Dog.objects.create(
            name="B-ZEUS CLARISSIMA STELLA", slug="search-b-zeus",
            is_public=False, sex=Dog.Sex.FEMALE,
        )
        DogRegistration.objects.create(dog=internal, number="REG-ZEUS-8831")
        self.client.force_login(self.moderator)
        queue = self.client.get(reverse("accounts:moderation"), {"q": "Zeus"})
        self.assertEqual(queue.status_code, 200)
        self.assertContains(queue, "Find any dog")
        self.assertContains(queue, "Search pending queue only")
        self.assertContains(queue, reverse("accounts:dog-edit-list"))
        # No member submission exists for either dog.
        finder = self.client.get(reverse("accounts:dog-edit-list"), {"q": "Zeus"})
        self.assertEqual(finder.status_code, 200)
        self.assertContains(finder, "B-ZEUS CLARISSIMA STELLA")
        self.assertContains(finder, str(internal.pk))
        self.assertContains(finder, "REG-ZEUS-8831")
        self.assertContains(finder, reverse("accounts:dog-direct-edit", args=[internal.pk]))
        self.assertContains(finder, reverse("accounts:reviewed-dog-health", args=[internal.pk]))
        self.assertIn(exact.pk, [item.pk for item in finder.context["dogs"]])
        self.assertIn(internal.pk, [item.pk for item in finder.context["dogs"]])

    def test_full_dog_search_supports_alias_registration_uuid_and_pagination(self):
        from registry.models import DogAlias, DogIdentityNumber, DogRegistration
        target = Dog.objects.create(name="Archive Corso", slug="archive-corso", is_public=False)
        DogAlias.objects.create(dog=target, name="Old Bloodline Name")
        DogRegistration.objects.create(dog=target, number="CANECORSO-712345")
        DogIdentityNumber.objects.create(dog=target, value="985 141 000 712345")
        self.client.force_login(self.moderator)
        url = reverse("accounts:dog-edit-list")
        for search_term in ("Old Bloodline", "CANECORSO-712345", str(target.pk), "985 141 000 712345"):
            with self.subTest(term=search_term):
                response = self.client.get(url, {"q": search_term})
                self.assertEqual(response.status_code, 200)
                self.assertIn(target.pk, [item.pk for item in response.context["dogs"]])

        Dog.objects.bulk_create([
            Dog(name=f"Pagination puppy {i:02d}", slug=f"pagination-puppy-{i:02d}")
            for i in range(31)
        ])
        page1 = self.client.get(url, {"q": "Pagination puppy"})
        page2 = self.client.get(url, {"q": "Pagination puppy", "page": "2"})
        self.assertEqual(page1.status_code, 200)
        self.assertEqual(page2.status_code, 200)
        self.assertEqual(len(page1.context["dogs"]), 25)
        self.assertEqual(len(page2.context["dogs"]), 6)
        self.assertContains(page1, "Next dogs")
        self.assertContains(page2, "Previous dogs")
        self.assertNotEqual(page1.context["dogs"][0].pk, page2.context["dogs"][0].pk)

        browse = self.client.get(url, {"browse": "1"})
        self.assertEqual(browse.status_code, 200)
        self.assertContains(browse, "All canonical dogs")
        self.assertTrue(browse.context["result_page"].paginator.count >= 33)
        self.assertEqual(self.client.get(url, {"q": "unlikely-query-xyz-9876"}).status_code, 200)
        self.assertContains(
            self.client.get(url, {"q": "unlikely-query-xyz-9876"}),
            "No matching canonical dogs",
        )

        self.client.force_login(self.member)
        self.assertEqual(self.client.get(url, {"q": "Corso"}).status_code, 403)
        self.assertEqual(self.client.get(url, {"browse": "1"}).status_code, 403)
