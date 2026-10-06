from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.template.loader import get_template
from django.test import TestCase
from django.urls import reverse

from .forms import SubmissionEvidenceForm


class MemberFormContrastRegressionTests(TestCase):
    def test_private_evidence_form_exposes_all_evidence_types(self):
        labels = [label for _value, label in SubmissionEvidenceForm().fields["evidence_type"].choices]

        self.assertIn("Pedigree certificate", labels)
        self.assertIn("Registration certificate", labels)
        self.assertIn("Breeding record", labels)
        self.assertIn("Litter record", labels)
        self.assertIn("Kennel documentation", labels)
        self.assertIn("DNA / parentage documentation", labels)
        self.assertIn("Identity photograph", labels)
        self.assertIn("Other supporting document", labels)

    def test_member_controls_follow_theme_instead_of_forcing_black_background(self):
        css_path = finders.find("core/site.css")
        self.assertIsNotNone(css_path)
        css = Path(css_path).read_text(encoding="utf-8")

        self.assertNotIn(
            ".form-field textarea,\n.merge-form select,\n.review-actions textarea {\n"
            "  width: 100%;\n  border: 1px solid var(--line-soft);\n"
            "  background: #090b0a;",
            css,
        )
        self.assertIn('input[type="file"]::file-selector-button', css)
        self.assertIn("select option,", css)


class ModerationTemplateRegressionTests(TestCase):
    def test_moderation_audit_template_compiles(self):
        template = get_template("accounts/moderation_audit.html")
        self.assertIsNotNone(template)

    def test_staff_can_render_moderation_audit(self):
        staff = get_user_model().objects.create_user(
            username="audit-template-staff",
            password="test-pass-123",
            is_staff=True,
        )
        self.client.force_login(staff)

        response = self.client.get(reverse("accounts:moderation-audit"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Audit history")
