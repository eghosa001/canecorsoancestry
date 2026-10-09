"""Protected canonical pedigree changes require a second authorized identity.

The test creates no production dog records. It checks that only an authorized
Super Admin can publish a moderator's protected ancestry proposal.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from registry.models import Dog, ModerationAudit, ModerationRoleAssignment


class ProtectedPedigreeChangeTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_superuser(
            username="ancestry-owner", email="ancestry-owner@example.test",
            password="valid-test-password",
        )
        self.mod = User.objects.create_user(username="ancestry-mod")
        self.second_mod = User.objects.create_user(username="ancestry-senior")
        ModerationRoleAssignment.objects.create(
            user=self.owner, role=ModerationRoleAssignment.Role.OWNER,
        )
        ModerationRoleAssignment.objects.create(
            user=self.mod, role=ModerationRoleAssignment.Role.REVIEWER,
            assigned_by=self.owner,
        )
        ModerationRoleAssignment.objects.create(
            user=self.second_mod, role=ModerationRoleAssignment.Role.SENIOR,
            assigned_by=self.owner,
        )
        self.dog = Dog.objects.create(
            name="Protected Test Dog", slug="protected-test-dog",
            sex=Dog.Sex.UNKNOWN, is_public=True,
        )
        self.editor = reverse("accounts:dog-direct-edit", args=[self.dog.pk])

    def payload(self, **fields):
        response = self.client.get(self.editor)
        self.assertEqual(response.status_code, 200)
        data = {
            "version": response.context["version"],
            "name": self.dog.name,
            "sex": self.dog.sex,
            "verification_state": self.dog.verification_state,
            "reason": "Reviewed original ancestry documentation",
        }
        for prefix, formset in response.context["formsets"].items():
            for field, value in formset.management_form.initial.items():
                data[f"{prefix}-{field}"] = str(value)
            for index, form in enumerate(formset.forms):
                for field in form.fields:
                    if field in {"DELETE", "dog"}:
                        continue
                    value = form[field].value()
                    if value is None or value is False or hasattr(value, "storage"):
                        continue
                    data[f"{prefix}-{index}-{field}"] = (
                        "on" if value is True else str(value)
                    )
        data.update(fields)
        return data

    def proposal(self):
        return ModerationAudit.objects.get(summary__kind="direct_dog_proposal")

    def review(self, reviewer, audit, decision, reason="Crosschecked pedigree evidence"):
        self.client.force_login(reviewer)
        return self.client.post(
            reverse("accounts:dog-review-edit", args=[self.dog.pk, audit.pk]),
            {"decision": decision, "reason": reason},
        )

    def test_pedigree_change_waits_for_superadmin_and_appears_after_approval(self):
        self.client.force_login(self.mod)
        response = self.client.post(self.editor, self.payload(sex=Dog.Sex.MALE))
        self.assertEqual(response.status_code, 302)
        self.dog.refresh_from_db()
        self.assertEqual(self.dog.sex, Dog.Sex.UNKNOWN)
        self.assertContains(self.client.get(reverse(
            "registry:dog-detail", args=[self.dog.slug],
        )), "Unknown")
        audit = self.proposal()
        self.assertEqual(audit.summary["proposed_changes"]["sex"], Dog.Sex.MALE)
        self.assertEqual(audit.actor, self.mod)
        self.assertContains(self.client.get(self.editor), "Awaiting Super Admin approval")

        result = self.review(self.second_mod, audit, "approve")
        self.assertEqual(result.status_code, 403)
        self.dog.refresh_from_db()
        self.assertEqual(self.dog.sex, Dog.Sex.UNKNOWN)
        result = self.review(self.owner, audit, "approve")
        self.assertEqual(result.status_code, 302)
        self.dog.refresh_from_db()
        self.assertEqual(self.dog.sex, Dog.Sex.MALE)
        self.assertContains(self.client.get(reverse(
            "registry:dog-detail", args=[self.dog.slug],
        )), "Male")
        self.assertEqual(ModerationAudit.objects.filter(
            summary__kind="direct_dog_proposal_approved",
            summary__original_audit_id=str(audit.pk),
        ).count(), 1)
        self.review(self.owner, audit, "approve")
        self.assertEqual(ModerationAudit.objects.filter(
            summary__kind="direct_dog_proposal_approved",
            summary__original_audit_id=str(audit.pk),
        ).count(), 1)

    def test_pedigree_parent_change_can_be_rejected_without_public_edit(self):
        sire = Dog.objects.create(name="Proposed Sire", slug="proposed-sire", sex=Dog.Sex.MALE)
        self.client.force_login(self.mod)
        response = self.client.post(self.editor, self.payload(sire_ref=str(sire.pk)))
        self.assertEqual(response.status_code, 302)
        self.dog.refresh_from_db()
        self.assertIsNone(self.dog.sire_id)
        audit = self.proposal()
        self.assertEqual(audit.summary["proposed_changes"]["sire"], str(sire.pk))
        self.assertEqual(self.review(self.owner, audit, "reject").status_code, 302)
        self.dog.refresh_from_db()
        self.assertIsNone(self.dog.sire_id)

    def test_ordinary_moderator_edit_still_updates_immediately(self):
        self.client.force_login(self.mod)
        response = self.client.post(self.editor, self.payload(colour="Brindle"))
        self.assertEqual(response.status_code, 302)
        self.dog.refresh_from_db()
        self.assertEqual(self.dog.colour, "Brindle")
        self.assertEqual(ModerationAudit.objects.filter(
            summary__kind="direct_dog_proposal",
        ).count(), 0)

    def test_sensitive_and_ordinary_edits_cannot_be_mixed(self):
        self.client.force_login(self.mod)
        response = self.client.post(self.editor, self.payload(
            sex=Dog.Sex.FEMALE, colour="Brindle",
        ))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Send protected ancestry changes for review separately")
        self.dog.refresh_from_db()
        self.assertEqual(self.dog.sex, Dog.Sex.UNKNOWN)
        self.assertEqual(self.dog.colour, "")
        self.assertFalse(ModerationAudit.objects.filter(
            summary__kind="direct_dog_proposal",
        ).exists())

    def test_superadmin_may_directly_edit_protected_ancestry_with_audit(self):
        self.client.force_login(self.owner)
        response = self.client.post(self.editor, self.payload(sex=Dog.Sex.MALE))
        self.assertEqual(response.status_code, 302)
        self.dog.refresh_from_db()
        self.assertEqual(self.dog.sex, Dog.Sex.MALE)
        self.assertTrue(ModerationAudit.objects.filter(
            summary__kind="direct_dog_edit",
        ).exists())
