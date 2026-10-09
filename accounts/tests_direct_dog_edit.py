"""Focused authorization, transaction, revision, and review coverage."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from registry.models import Dog, DogTitle, ModerationAudit, ModerationRoleAssignment


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
            "reason": "Corrected against the documented dog record",
        }
        for name, formset in response.context["formsets"].items():
            for field, value in formset.management_form.initial.items():
                payload[f"{name}-{field}"] = str(value)
            for index, form in enumerate(formset.forms):
                if not form.instance.pk:
                    continue
                payload[f"{name}-{index}-id"] = str(form.instance.pk)
                for field_name in form.fields:
                    if field_name in {"id", "DELETE", "dog"}:
                        continue
                    value = getattr(form.instance, field_name, None)
                    if value is None or value is False:
                        continue
                    if hasattr(value, "pk"):
                        value = value.pk
                    if hasattr(value, "name") and hasattr(value, "storage"):
                        continue
                    payload[f"{name}-{index}-{field_name}"] = str(value)
        payload.update(updates)
        return payload

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
            self.editor(), self.submission(name="Mistaken Name", **{"titles-0-name": "Wrong title"})
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
