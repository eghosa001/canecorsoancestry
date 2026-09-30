from datetime import date
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from registry.data_quality import full_quality_report
from registry.models import Dog


class PedigreeIntegrityHardeningTests(TestCase):
    def test_parent_cycle_is_rejected_on_edit(self):
        parent = Dog.objects.create(
            name="Cycle Parent",
            slug="cycle-parent",
            sex=Dog.Sex.MALE,
        )
        child = Dog.objects.create(
            name="Cycle Child",
            slug="cycle-child",
            sire=parent,
        )

        parent.sire = child
        with self.assertRaises(ValidationError):
            parent.full_clean()

    def test_parent_sex_and_date_conflicts_are_rejected(self):
        female = Dog.objects.create(
            name="Female Parent",
            slug="female-parent-hardening",
            sex=Dog.Sex.FEMALE,
            date_of_birth=date(2022, 1, 1),
        )
        child = Dog(
            name="Impossible Child",
            slug="impossible-child-hardening",
            date_of_birth=date(2021, 1, 1),
            sire=female,
        )

        with self.assertRaises(ValidationError) as context:
            child.full_clean()

        self.assertIn("sire", context.exception.message_dict)

    def test_normalized_name_updates_with_name(self):
        dog = Dog.objects.create(
            name="Custodi-Nos Kárma",
            slug="normalized-hardening",
        )
        self.assertEqual(dog.normalized_name, "custodinoskarma")

        dog.name = "Custodi Nos Karma II"
        dog.save(update_fields=("name",))
        dog.refresh_from_db()
        self.assertEqual(dog.normalized_name, "custodinoskarmaii")


class DataQualityAuditTests(TestCase):
    def test_audit_detects_legacy_integrity_conflicts(self):
        female = Dog.objects.create(
            name="Audit Female",
            slug="audit-female-hardening",
            sex=Dog.Sex.FEMALE,
        )
        # save() deliberately does not call full_clean(), so this simulates
        # legacy/imported corruption that the audit must still detect.
        Dog.objects.create(
            name="Audit Child",
            slug="audit-child-hardening",
            sire=female,
            is_public=True,
        )

        report = full_quality_report()
        self.assertEqual(report["counts"]["sire_sex_conflicts"], 1)
        self.assertGreaterEqual(report["critical_count"], 1)

        out = StringIO()
        with self.assertRaises(Exception):
            call_command("audit_pedigree_data", "--fail-on-critical", stdout=out)


class DataHealthDashboardTests(TestCase):
    def test_staff_can_open_data_health_dashboard(self):
        staff = get_user_model().objects.create_user(
            username="data-health-staff",
            password="test-pass-123",
            is_staff=True,
        )
        self.client.force_login(staff)
        response = self.client.get(reverse("accounts:data-health"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pedigree data health")

    def test_member_cannot_open_data_health_dashboard(self):
        member = get_user_model().objects.create_user(
            username="data-health-member",
            password="test-pass-123",
        )
        self.client.force_login(member)
        response = self.client.get(reverse("accounts:data-health"))
        self.assertEqual(response.status_code, 302)
