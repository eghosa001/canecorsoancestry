from django.contrib.auth import get_user_model
from django.template.loader import get_template
from django.test import TestCase
from django.urls import reverse

from registry.models import Dog, HealthRecord, ModerationAudit, ModerationRoleAssignment, VerificationState


class ModerationTemplateRegressionTests(TestCase):
    def test_moderation_audit_template_compiles(self):
        template = get_template("accounts/moderation_audit.html")
        self.assertIsNotNone(template)

    def test_moderator_can_render_moderation_audit(self):
        staff = get_user_model().objects.create_user(
            username="audit-template-staff",
            password="test-pass-123",
        )
        ModerationRoleAssignment.objects.create(
            user=staff,
            role=ModerationRoleAssignment.Role.REVIEWER,
        )
        self.client.force_login(staff)

        response = self.client.get(reverse("accounts:moderation-audit"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Audit history")

    def test_audit_history_offers_dog_and_health_edit_shortcuts(self):
        staff = get_user_model().objects.create_user(
            username="audit-health-staff", password="test-pass-123",
        )
        ModerationRoleAssignment.objects.create(
            user=staff, role=ModerationRoleAssignment.Role.REVIEWER,
        )
        dog = Dog.objects.create(name="Audit health dog", slug="audit-health-dog")
        health = HealthRecord.objects.create(
            dog=dog, test_type="Hip score", result="HD-A",
            verification_state=VerificationState.HEALTH_VERIFIED,
        )
        ModerationAudit.objects.create(
            action=ModerationAudit.Action.VERIFICATION, actor=staff, dog=dog,
            summary={
                "kind": "historical_health_evidence",
                "health_record_id": health.pk,
            },
        )
        self.client.force_login(staff)
        response = self.client.get(reverse("accounts:moderation-audit"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, reverse("accounts:dog-direct-edit", args=[dog.pk]),
        )
        self.assertContains(
            response, reverse("accounts:reviewed-dog-health", args=[dog.pk]),
        )
        self.assertContains(
            response, reverse("accounts:edit-reviewed-health-result", args=[dog.pk, health.pk]),
        )
        self.assertContains(response, "without a member request")
        self.assertEqual(
            self.client.get(reverse("accounts:edit-reviewed-health-result", args=[dog.pk, health.pk])).status_code,
            200,
        )

        # Staff-only editing is enforced at the destination, not by hiding links alone.
        member = get_user_model().objects.create_user(
            username="audit-health-member", password="test-pass-123",
        )
        self.client.force_login(member)
        self.assertEqual(
            self.client.get(reverse("accounts:moderation-audit")).status_code, 403,
        )
        self.assertEqual(
            self.client.get(reverse("accounts:edit-reviewed-health-result", args=[dog.pk, health.pk])).status_code,
            403,
        )

    def test_super_admin_evidence_table_links_to_verified_value_editor(self):
        admin = get_user_model().objects.create_superuser(
            username="audit-health-admin", email="audit-health-admin@example.test",
            password="test-pass-123",
        )
        dog = Dog.objects.create(name="Historical lab dog", slug="historical-lab-dog")
        health = HealthRecord.objects.create(
            dog=dog, test_type="Elbow score", result="ED-0",
            verification_state=VerificationState.HEALTH_VERIFIED,
        )
        self.client.force_login(admin)
        response = self.client.get(reverse("accounts:health-genetic-dog", args=[dog.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Edit verified result")
        self.assertContains(
            response, reverse("accounts:edit-reviewed-health-result", args=[dog.pk, health.pk]),
        )
