"""Staff final card publication, manual corrections and source-document safety."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from registry.models import (
    BreedDNAReport, Dog, DogDocument, HealthRecord, Kennel,
    ModerationAudit, ModerationRoleAssignment, Submission, VerificationState,
)


class ModeratorFinalPublicationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.moderator = User.objects.create_user(username="final-mod", password="securepass123")
        self.member = User.objects.create_user(username="final-member", password="securepass123")
        ModerationRoleAssignment.objects.create(
            user=self.moderator, role=ModerationRoleAssignment.Role.REVIEWER,
        )
        self.kennel = Kennel.objects.create(
            name="Final health kennel", slug="final-health-kennel", verified_at=timezone.now(),
        )
        self.dog = Dog.objects.create(
            name="Final Health Dog", slug="final-health-dog",
            kennel=self.kennel, is_public=True,
        )
        self.record = HealthRecord.objects.create(
            dog=self.dog, test_type="DSRA", result="Clear",
            verification_state=VerificationState.HEALTH_VERIFIED, is_public=False,
        )
        self.edit_url = reverse(
            "accounts:edit-reviewed-health-result", args=[self.dog.pk, self.record.pk],
        )
        self.public_url = reverse("registry:dog-detail", args=[self.dog.slug])

    def test_only_moderators_can_edit_a_post_approval_result(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(self.edit_url).status_code, 403)
        self.assertEqual(self.client.post(self.edit_url, {"intent": "publish"}).status_code, 403)
        self.client.force_login(self.moderator)
        page = self.client.get(self.edit_url)
        self.assertContains(page, "Save changes")
        self.assertNotContains(page, "Save &amp; publish on dog profile")
        self.assertContains(page, "Live preview of your edited result")

    def test_post_approval_edit_and_explicit_publish_change_the_frontend(self):
        self.assertNotContains(self.client.get(self.public_url), 'genetic-screening-status--clear')
        self.client.force_login(self.moderator)
        response = self.client.post(self.edit_url, {
            "intent": "publish", "test_type": "DSRA",
            "result": "Carrier", "tested_on": "2026-10-19", "reviewed": "on",
        })
        self.assertRedirects(
            response, reverse("accounts:reviewed-dog-health", args=[self.dog.pk]),
        )
        self.record.refresh_from_db()
        self.assertEqual(self.record.result, "Carrier")
        self.assertTrue(self.record.is_public)
        self.assertContains(self.client.get(self.public_url), 'genetic-screening-status--carrier')
        self.assertTrue(ModerationAudit.objects.filter(
            dog=self.dog, summary__kind="moderator_post_approval_health_editor"
        ).exists())

        # Saving a correction privately immediately withdraws it from the public profile.
        self.client.post(self.edit_url, {
            "intent": "save", "test_type": "DSRA",
            "result": "Clear", "reviewed": "on",
        })
        self.record.refresh_from_db()
        self.assertFalse(self.record.is_public)
        self.assertNotContains(self.client.get(self.public_url), 'genetic-screening-status--clear')

    def test_invalid_genetic_result_or_missing_attestation_never_publish(self):
        self.client.force_login(self.moderator)
        response = self.client.post(self.edit_url, {
            "intent": "publish", "test_type": "DSRA",
            "result": "Probably fine", "reviewed": "on",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Choose Clear, Carrier, Affected, Inconclusive or Not tested")
        response = self.client.post(self.edit_url, {
            "intent": "publish", "test_type": "DSRA", "result": "Carrier",
        })
        self.assertEqual(response.status_code, 200)
        self.record.refresh_from_db()
        self.assertEqual(self.record.result, "Clear")
        self.assertFalse(self.record.is_public)

    def test_breed_percentage_edit_updates_structured_card_without_exposing_original(self):
        document = DogDocument.objects.create(
            dog=self.dog, title="DNA certificate", document_type="dna",
            file="private/documents/final-lab.pdf", is_public=False,
            staff_review_only=True, submitted_by=self.moderator,
        )
        record = HealthRecord.objects.create(
            dog=self.dog, test_type="DNA breed composition", result="100% Cane Corso",
            verification_state=VerificationState.HEALTH_VERIFIED, is_public=False,
        )
        report = BreedDNAReport.objects.create(
            health_record=record, evidence_document=document,
            provider="Embark", cane_corso_percentage="100.00",
            composition=[{"breed": "Cane Corso", "percentage": "100"}],
            consent_public_summary=True,
        )
        url = reverse("accounts:edit-reviewed-health-result", args=[self.dog.pk, record.pk])
        self.client.force_login(self.moderator)
        response = self.client.post(url, {
            "intent": "publish", "reviewed": "on",
            "laboratory": "Embark", "breed_percentage": "92.50",
            "other_breeds": "Boxer: 7.50",
        })
        self.assertEqual(response.status_code, 302)
        report.refresh_from_db()
        record.refresh_from_db()
        document.refresh_from_db()
        self.assertTrue(record.is_public)
        self.assertEqual(report.provider, "Embark")
        self.assertEqual(str(report.cane_corso_percentage), "92.50")
        self.assertEqual(report.composition[1]["breed"], "Boxer")
        self.assertFalse(document.is_public)
        self.assertEqual(document.file.name, "private/documents/final-lab.pdf")
        self.assertContains(self.client.get(self.public_url), 'class="breed-dna-score">92.5')

    def test_breed_publication_blocked_without_owner_consent(self):
        document = DogDocument.objects.create(
            dog=self.dog, title="Private report", document_type="dna",
            file="private/documents/restricted.pdf", is_public=False,
            staff_review_only=True, submitted_by=self.moderator,
        )
        record = HealthRecord.objects.create(
            dog=self.dog, test_type="DNA breed composition", result="100% Cane Corso",
            verification_state=VerificationState.HEALTH_VERIFIED, is_public=False,
        )
        BreedDNAReport.objects.create(
            health_record=record, evidence_document=document,
            provider="Embark", cane_corso_percentage="100.00",
            composition=[{"breed": "Cane Corso", "percentage": "100"}],
            consent_public_summary=False,
        )
        url = reverse("accounts:edit-reviewed-health-result", args=[self.dog.pk, record.pk])
        self.client.force_login(self.moderator)
        response = self.client.post(url, {
            "intent": "publish", "reviewed": "on",
            "laboratory": "Embark", "breed_percentage": "100",
        })
        self.assertEqual(response.status_code, 200)
        record.refresh_from_db()
        self.assertFalse(record.is_public)
        self.assertContains(response, "owner has not authorized publication")

    def test_add_omitted_condition_from_approved_evidence_is_private_until_published(self):
        source = Submission.objects.create(
            kind=Submission.Kind.HEALTH, dog=self.dog, submitted_by=self.member,
            status=Submission.Status.APPROVED, attachment="health/private-source.pdf",
            payload={"test_type": "Other test", "result": "Reviewed"},
        )
        self.client.force_login(self.moderator)
        add_url = reverse("accounts:add-reviewed-health-condition", args=[self.dog.pk])
        response = self.client.post(add_url, {
            "source_submission": str(source.pk), "test_type": "Novel hereditary condition",
            "result": "Carrier", "reviewed": "on",
        })
        self.assertEqual(response.status_code, 302)
        new = HealthRecord.objects.get(dog=self.dog, test_type="Novel hereditary condition")
        self.assertTrue(new.is_public)
        self.assertIn(str(source.pk), new.notes)
        self.assertTrue(ModerationAudit.objects.filter(
            dog=self.dog, summary__kind="additional_health_condition",
        ).exists())
        self.assertContains(self.client.get(self.public_url), "Novel hereditary condition")
        self.client.post(
            reverse("accounts:toggle-health-result", args=[self.dog.pk, new.pk]),
            {"visibility": "show"},
        )
        public = self.client.get(self.public_url)
        self.assertContains(public, "Novel hereditary condition")
        self.assertContains(public, "Additional laboratory screening")
        self.assertContains(public, "genetic-screening-status--carrier")
        self.assertNotContains(public, "private-source.pdf")


    def test_moderator_senior_admin_and_super_admin_can_publish_separate_health_statuses(self):
        User = get_user_model()
        senior = User.objects.create_user(username="status-senior")
        ModerationRoleAssignment.objects.create(
            user=senior, role=ModerationRoleAssignment.Role.SENIOR,
        )
        super_admin = User.objects.create_superuser(
            username="status-super-admin", email="staff-tests@example.org", password="securepass123"
        )
        source = Submission.objects.create(
            kind=Submission.Kind.HEALTH, dog=self.dog,
            submitted_by=self.member, status=Submission.Status.APPROVED,
            attachment="health/verified-dna.pdf",
            payload={"test_type": "DNA panel", "result": "Reviewed"},
        )
        scenarios = (
            (self.moderator, "Custom marker 1", "Clear"),
            (senior, "Custom marker 2", "Carrier"),
            (super_admin, "Custom marker 3", "Affected"),
        )
        for actor, condition, result in scenarios:
            with self.subTest(role=actor.username):
                self.client.force_login(actor)
                response = self.client.post(
                    reverse("accounts:add-reviewed-health-condition", args=[self.dog.pk]),
                    {
                        "source_submission": str(source.pk),
                        "test_type": condition, "result": result, "reviewed": "on",
                    },
                )
                self.assertEqual(response.status_code, 302)
                record = HealthRecord.objects.get(dog=self.dog, test_type=condition)
                self.assertTrue(record.is_public)
                response = self.client.post(
                    reverse("accounts:edit-reviewed-health-result", args=[self.dog.pk, record.pk]),
                    {
                        "intent": "publish", "test_type": condition,
                        "result": result, "reviewed": "on",
                    },
                )
                self.assertEqual(response.status_code, 302)
                record.refresh_from_db()
                self.assertTrue(record.is_public)
                self.assertContains(self.client.get(self.public_url), condition)
                self.assertContains(self.client.get(self.public_url), result)

    def test_staff_reviewed_laboratory_document_can_supply_multiple_conditions(self):
        document = DogDocument.objects.create(
            dog=self.dog, title="Private laboratory test panel",
            document_type=DogDocument.DocumentType.HEALTH,
            file="private/documents/staff-source.pdf", is_public=False,
            staff_review_only=True, submitted_by=self.moderator,
        )
        HealthRecord.objects.create(
            dog=self.dog, test_type="Panel overview", result="Verified",
            verification_state=VerificationState.HEALTH_VERIFIED,
            evidence_document=document, is_public=False,
        )
        self.client.force_login(self.moderator)
        response = self.client.post(
            reverse("accounts:add-reviewed-health-condition", args=[self.dog.pk]),
            {
                "source_document": str(document.pk), "test_type": "Novel retinal condition",
                "result": "Inconclusive", "reviewed": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        record = HealthRecord.objects.get(dog=self.dog, test_type="Novel retinal condition")
        self.assertTrue(record.is_public)
        self.assertIn(str(document.pk), record.notes)
        self.client.post(
            reverse("accounts:toggle-health-result", args=[self.dog.pk, record.pk]),
            {"visibility": "show"},
        )
        page = self.client.get(self.public_url)
        self.assertContains(page, "Novel retinal condition")
        self.assertContains(page, "Inconclusive")
        self.assertNotContains(page, "staff-source.pdf")

    def test_unapproved_or_missing_laboratory_source_cannot_create_clear_result(self):
        self.client.force_login(self.moderator)
        response = self.client.post(
            reverse("accounts:add-reviewed-health-condition", args=[self.dog.pk]),
            {"test_type": "DSRA", "result": "Clear", "reviewed": "on"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(HealthRecord.objects.filter(dog=self.dog, test_type="DSRA", result="Clear", notes__startswith="Moderator condition").exists())
