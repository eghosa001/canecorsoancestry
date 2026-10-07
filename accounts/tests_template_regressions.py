from django.contrib.auth import get_user_model
from django.template.loader import get_template
from django.test import TestCase
from django.urls import reverse

from registry.models import ModerationRoleAssignment


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
