"""Focused moderator transcription, visibility, role and evidence privacy tests."""
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from registry.models import (
    BreedDNAReport, Dog, DogDocument, HealthRecord, Kennel, KennelMembership,
    ModerationRoleAssignment, Submission, VerificationState,
)
from registry.services import approve_submission


class ModeratorLabResultTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="health-owner", password="abc123xyz")
        self.moderator = User.objects.create_user(username="health-moderator", password="abc123xyz")
        self.unauthorized = User.objects.create_user(username="unrelated-member", password="abc123xyz")
        ModerationRoleAssignment.objects.create(
            user=self.moderator, role=ModerationRoleAssignment.Role.REVIEWER
        )
        self.kennel = Kennel.objects.create(
            name="Moderation health kennel", slug="moderation-health-kennel",
            verified_at=timezone.now(),
        )
        KennelMembership.objects.create(
            user=self.owner, kennel=self.kennel, role=KennelMembership.Role.OWNER
        )
        self.dog = Dog.objects.create(
            name="Moderator Lab Dog", slug="moderator-lab-dog",
            kennel=self.kennel, is_public=True,
        )
        self.submit_url = reverse("accounts:submit-health-record", args=[self.dog.pk])
        self.public_url = reverse("registry:dog-detail", args=[self.dog.slug])
        self.health_url = reverse("accounts:reviewed-dog-health", args=[self.dog.pk])

    def upload(self, kind="health"):
        self.client.force_login(self.owner)
        response = self.client.post(self.submit_url, {
            "evidence_type": kind, "test_type": "Hip scores",
            "result": "A", "attachment": SimpleUploadedFile(
                "health-scan.pdf", b"%PDF-1.4\n% test evidence\n", content_type="application/pdf"
            ),
        })
        self.assertEqual(response.status_code, 302)
        return Submission.objects.get(kind=Submission.Kind.HEALTH)

    def test_no_report_means_no_available_records(self):
        page = self.client.get(self.public_url)
        self.assertContains(page, "No available records")
        self.assertNotContains(page, "genetic-screening-status--clear")

    def test_moderator_transcribes_one_image_into_three_separate_results(self):
        submission = self.upload()
        self.client.force_login(self.moderator)
        edit_url = reverse("accounts:transcribe-health-submission", args=[submission.pk])
        response = self.client.post(edit_url, {
            "publish_primary": "", "reviewed": "on",
            "status_DSRA": "Clear", "publish_DSRA": "on",
            "status_NCL1": "Carrier", "publish_NCL1": "on",
            "status_CMR1": "Affected",
        })
        self.assertEqual(response.status_code, 302)
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.PENDING)
        self.assertEqual(submission.payload["reviewed_markers"]["NCL1"]["status"], "Carrier")
        self.assertNotContains(self.client.get(self.public_url), "genetic-screening-status--carrier")
        approve_submission(submission, self.moderator)
        records = HealthRecord.objects.filter(dog=self.dog)
        self.assertEqual(records.count(), 4)
        self.assertTrue(records.get(test_type="Hip scores").is_public)
        self.assertTrue(records.get(test_type="CMR1").is_public)
        self.assertTrue(records.get(test_type="DSRA").is_public)
        self.assertTrue(records.get(test_type="NCL1").is_public)
        doc = DogDocument.objects.get(source_submission=submission)
        self.assertFalse(doc.is_public)
        self.client.logout()
        public = self.client.get(self.public_url)
        self.assertContains(public, "genetic-screening-status--clear")
        self.assertContains(public, "genetic-screening-status--carrier")
        self.assertNotContains(public, "genetic-screening-status--untested")
        self.assertNotContains(public, "health-scan.jpg")

    def test_staff_can_hide_and_restore_only_reviewed_summary(self):
        submission = self.upload()
        self.client.force_login(self.moderator)
        approve_submission(submission, self.moderator)
        record = HealthRecord.objects.get(dog=self.dog)
        self.assertTrue(record.is_public)
        action = reverse("accounts:toggle-health-result", args=[self.dog.pk, record.pk])
        self.assertEqual(self.client.post(action, {"visibility": "hide"}).status_code, 302)
        self.client.logout()
        self.assertContains(self.client.get(self.public_url), "No available records")
        self.client.force_login(self.moderator)
        self.assertEqual(self.client.post(action, {"visibility": "show"}).status_code, 302)
        self.client.logout()
        self.assertContains(self.client.get(self.public_url), "Hip scores")
        self.client.force_login(self.unauthorized)
        self.assertEqual(self.client.get(self.health_url).status_code, 403)
        self.assertEqual(self.client.post(action, {"visibility": "hide"}).status_code, 403)

    def test_never_publish_original_health_image(self):
        submission = self.upload()
        self.client.force_login(self.moderator)
        approve_submission(submission, self.moderator)
        doc = DogDocument.objects.get(source_submission=submission)
        # Even if a legacy doc flag is mistakenly set True, the private-media
        # access gate must prevent external access.
        doc.is_public = True
        doc.save(update_fields=["is_public"])
        from core.media_views import _can_read_media
        self.assertEqual(_can_read_media(self.unauthorized, doc.file.name), (False, False))
        self.client.logout()
        self.assertNotContains(self.client.get(self.public_url), "View owner-authorized DNA report")

    def test_staff_cannot_publish_breed_report_without_owner_consent(self):
        report = HealthRecord.objects.create(
            dog=self.dog, test_type="DNA breed composition", result="100% Cane Corso",
            verification_state=VerificationState.HEALTH_VERIFIED, is_public=False,
        )
        evidence = DogDocument.objects.create(
            dog=self.dog, title="private lab", document_type="dna",
            file="private/documents/genetic.pdf", is_public=False,
            staff_review_only=True, submitted_by=self.moderator,
        )
        BreedDNAReport.objects.create(
            health_record=report, evidence_document=evidence,
            provider="Embark", cane_corso_percentage="100.00",
            composition=[{"breed": "Cane Corso", "percentage": "100"}],
            consent_public_summary=False,
        )
        self.client.force_login(self.moderator)
        action = reverse("accounts:toggle-health-result", args=[self.dog.pk, report.pk])
        self.assertEqual(self.client.post(action, {"visibility": "show"}).status_code, 302)
        report.refresh_from_db()
        self.assertFalse(report.is_public)
        self.client.logout()
        self.assertNotContains(self.client.get(self.public_url), "100% Cane Corso")

    def test_incomplete_lab_transcription_is_rejected(self):
        submission = self.upload()
        self.client.force_login(self.moderator)
        url = reverse("accounts:transcribe-health-submission", args=[submission.pk])
        self.client.post(url, {"status_CMR1": "", "publish_CMR1": "on", "reviewed": "on"})
        submission.refresh_from_db()
        self.assertNotIn("reviewed_markers", submission.payload)

    def test_approved_health_document_allows_moderator_numeric_entry_and_is_private(self):
        accepted = Submission.objects.create(
            kind=Submission.Kind.DOCUMENT, status=Submission.Status.APPROVED,
            dog=self.dog, submitted_by=self.owner,
            payload={"document_type": DogDocument.DocumentType.HEALTH},
        )
        evidence = DogDocument.objects.create(
            dog=self.dog, title="Accepted health laboratory report",
            document_type=DogDocument.DocumentType.HEALTH,
            file="documents/accepted-elbow-evidence.pdf", is_public=True,
            source_submission=accepted, submitted_by=self.owner,
        )
        self.client.force_login(self.moderator)
        self.assertContains(self.client.get(self.health_url), "Accepted health laboratory report")
        url = reverse("accounts:add-reviewed-health-condition", args=[self.dog.pk])
        response = self.client.post(url, {
            "source_document": str(evidence.pk), "test_type": "Elbow measurement",
            "result": "", "numeric_value": "12.50", "result_unit": "mm",
            "reviewed": "on",
        })
        self.assertEqual(response.status_code, 302)
        record = HealthRecord.objects.get(dog=self.dog, test_type="Elbow measurement")
        self.assertEqual(record.result, "12.50 mm")
        self.assertEqual(record.verification_state, VerificationState.HEALTH_VERIFIED)
        self.assertTrue(record.is_public)
        self.assertEqual(record.evidence_document, evidence)
        evidence.refresh_from_db()
        self.assertFalse(evidence.is_public)
        from core.media_views import _can_read_media
        self.assertEqual(_can_read_media(self.unauthorized, evidence.file.name), (False, False))
        self.client.logout()
        public = self.client.get(self.public_url)
        self.assertContains(public, "12.50 mm")
        self.assertContains(public, "Other health results")
        self.assertContains(public, "Verified")
        self.assertNotContains(public, "Additional laboratory screening")

    def test_moderator_can_correct_accepted_health_value_and_non_staff_cannot(self):
        submission = self.upload()
        self.client.force_login(self.moderator)
        approve_submission(submission, self.moderator)
        record = HealthRecord.objects.get(dog=self.dog)
        url = reverse("accounts:edit-reviewed-health-result", args=[self.dog.pk, record.pk])
        response = self.client.post(url, {
            "intent": "publish", "test_type": "Elbow measurement",
            "result": "", "numeric_value": "0", "result_unit": "mm",
            "reviewed": "on",
        })
        self.assertEqual(response.status_code, 302)
        record.refresh_from_db()
        self.assertEqual(record.result, "0 mm")
        self.assertEqual(record.verification_state, VerificationState.HEALTH_VERIFIED)
        self.assertTrue(record.is_public)
        self.client.force_login(self.unauthorized)
        self.assertEqual(self.client.post(url, {
            "intent": "publish", "test_type": "Elbow measurement",
            "result": "5", "reviewed": "on",
        }).status_code, 403)
        record.refresh_from_db()
        self.assertEqual(record.result, "0 mm")


    def test_approved_submission_links_to_edit_and_repeated_corrections_preserve_source(self):
        submission = self.upload()
        self.client.force_login(self.moderator)
        approve_submission(submission, self.moderator)
        record = HealthRecord.objects.get(dog=self.dog)
        original_attachment = submission.attachment.name
        original_payload = dict(submission.payload)
        evidence = DogDocument.objects.get(source_submission=submission)

        detail = self.client.get(
            reverse("accounts:moderation-submission", args=[submission.pk])
        )
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Correct this dog's approved health results")
        self.assertContains(detail, "Edit approved health values")
        self.assertContains(detail, self.health_url + "#approved-health-results")
        health = self.client.get(self.health_url)
        self.assertContains(health, 'id="approved-health-results"')
        edit = reverse(
            "accounts:edit-reviewed-health-result", args=[self.dog.pk, record.pk]
        )
        self.assertContains(health, edit)

        for result in ("B", "A"):
            response = self.client.post(edit, {
                "intent": "publish", "test_type": "Hip scores",
                "result": result, "reviewed": "on",
            })
            self.assertRedirects(response, self.health_url)
            record.refresh_from_db()
            self.assertEqual(record.result, result)
        self.assertEqual(record.verification_state, VerificationState.HEALTH_VERIFIED)
        public = self.client.get(self.public_url)
        self.assertContains(public, "<strong>Hip scores</strong>", html=True)
        self.assertContains(public, 'A <small class="muted">')
        submission.refresh_from_db()
        evidence.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.APPROVED)
        self.assertEqual(submission.attachment.name, original_attachment)
        self.assertEqual(submission.payload, original_payload)
        self.assertFalse(evidence.is_public)

    def test_approved_document_links_to_health_transcription_not_raw_document_edit(self):
        submission = Submission.objects.create(
            kind=Submission.Kind.DOCUMENT, status=Submission.Status.APPROVED,
            dog=self.dog, submitted_by=self.owner,
            payload={"document_type": DogDocument.DocumentType.HEALTH},
        )
        self.client.force_login(self.moderator)
        detail = self.client.get(
            reverse("accounts:moderation-submission", args=[submission.pk])
        )
        self.assertContains(detail, "Enter or correct values from this approved report")
        self.assertContains(detail, self.health_url + "#add-approved-condition")

    def test_public_profile_staff_correction_link_is_not_available_to_member(self):
        submission = self.upload()
        self.client.force_login(self.moderator)
        approve_submission(submission, self.moderator)
        self.assertContains(self.client.get(self.public_url), "Edit verified health values")
        self.assertContains(self.client.get(self.public_url), self.health_url + "#approved-health-results")
        self.client.force_login(self.unauthorized)
        self.assertNotContains(self.client.get(self.public_url), "Edit verified health values")
        self.assertEqual(self.client.get(self.health_url).status_code, 403)

    def test_approved_health_record_has_one_edit_flow_and_live_preview(self):
        submission = self.upload()
        self.client.force_login(self.moderator)
        approve_submission(submission, self.moderator)
        record = HealthRecord.objects.get(dog=self.dog)
        list_page = self.client.get(self.health_url)
        self.assertContains(list_page, "Edit health record")
        self.assertNotContains(list_page, "Edit &amp; preview")
        url = reverse("accounts:edit-reviewed-health-result", args=[self.dog.pk, record.pk])
        edit_page = self.client.get(url)
        self.assertEqual(edit_page.status_code, 200)
        self.assertContains(edit_page, "Live preview of your edited result")
        self.assertContains(edit_page, "Save changes")
        self.assertContains(edit_page, "Original laboratory result")

    def test_visible_health_result_matches_public_profile_and_exact_dog_identity(self):
        dog = Dog.objects.create(
            name="B-ZEUS CLARISSIMA STELLA",
            slug="b-zeus-publication-consistency",
            is_public=True,
        )
        record = HealthRecord.objects.create(
            dog=dog, test_type="Hip screening",
            result="HD-A", is_public=True,
            verification_state=VerificationState.HEALTH_VERIFIED,
        )
        self.client.force_login(self.moderator)
        health = self.client.get(reverse("accounts:reviewed-dog-health", args=[dog.pk]))
        self.assertContains(health, "Visible on public profile")
        self.assertContains(health, str(dog.pk))
        self.assertContains(health, reverse("registry:dog-detail", args=[dog.slug]))
        self.assertContains(health, reverse("accounts:edit-reviewed-health-result", args=[dog.pk, record.pk]))
        public = self.client.get(reverse("registry:dog-detail", args=[dog.slug]))
        self.assertContains(public, "Hip &amp; elbow health")
        self.assertContains(public, "HD-A")

    def test_misleading_public_flag_reports_why_result_is_not_on_site(self):
        from registry.health_publication import publication_status
        dog = Dog.objects.create(
            name="Unavailable health dog", slug="unavailable-health-dog",
            is_public=True,
        )
        legacy = HealthRecord.objects.create(
            dog=dog, test_type="Breed DNA purity",
            result="100% Cane Corso", is_public=True,
            verification_state=VerificationState.HEALTH_VERIFIED,
        )
        self.assertEqual(publication_status(legacy)[0], "needs_structuring")
        self.client.force_login(self.moderator)
        health = self.client.get(reverse("accounts:reviewed-dog-health", args=[dog.pk]))
        self.assertContains(health, "Not visible — correct the result")
        self.assertContains(health, "owner-authorized")
        public = self.client.get(reverse("registry:dog-detail", args=[dog.slug]))
        self.assertNotContains(public, "100% Cane Corso")

        dog.is_public = False
        dog.save(update_fields=["is_public"])
        self.assertEqual(publication_status(legacy)[0], "dog_hidden")
        health = self.client.get(reverse("accounts:reviewed-dog-health", args=[dog.pk]))
        self.assertContains(health, "This dog's public profile is not visible")

        # No private health report ever becomes a public media attachment.
        self.assertEqual(legacy.evidence_document_id, None)

    def test_data_health_inventory_finds_public_flags_hidden_by_profile_rules(self):
        dog = Dog.objects.create(
            name="Staff visibility mismatch", slug="staff-visibility-mismatch",
            is_public=True,
        )
        HealthRecord.objects.create(
            dog=dog, test_type="Breed DNA purity",
            result="Unstructured", is_public=True,
            verification_state=VerificationState.HEALTH_VERIFIED,
        )
        self.client.force_login(self.moderator)
        response = self.client.get(reverse("accounts:data-health"), {"health_visibility": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Staff visibility mismatch")
        self.assertContains(response, "Not visible — correct the result")
        self.assertGreaterEqual(response.context["health_visibility_totals"]["mismatch"], 1)

    def test_unverified_legacy_records_remain_separate_from_approved_editor(self):
        record = HealthRecord.objects.create(
            dog=self.dog, test_type="Legacy hip claim", result="A",
            verification_state=VerificationState.COMMUNITY, is_public=True,
        )
        self.client.force_login(self.moderator)
        edit = reverse("accounts:edit-reviewed-health-result", args=[self.dog.pk, record.pk])
        health = self.client.get(self.health_url)
        self.assertNotContains(health, edit)
        self.assertContains(health, "not evidence-verified")
        self.assertEqual(self.client.get(edit).status_code, 403)

    def test_numeric_result_does_not_bypass_genetic_marker_validation(self):
        accepted = Submission.objects.create(
            kind=Submission.Kind.DOCUMENT, status=Submission.Status.APPROVED,
            dog=self.dog, submitted_by=self.owner,
            payload={"document_type": DogDocument.DocumentType.DNA},
        )
        evidence = DogDocument.objects.create(
            dog=self.dog, title="Accepted DNA report",
            document_type=DogDocument.DocumentType.DNA,
            file="documents/accepted-dna-evidence.pdf", source_submission=accepted,
            submitted_by=self.owner,
        )
        self.client.force_login(self.moderator)
        url = reverse("accounts:add-reviewed-health-condition", args=[self.dog.pk])
        self.assertEqual(self.client.post(url, {
            "source_document": str(evidence.pk), "test_type": "DSRA",
            "result": "", "numeric_value": "1", "reviewed": "on",
        }).status_code, 302)
        self.assertFalse(HealthRecord.objects.filter(dog=self.dog, test_type="DSRA").exists())

    def test_super_admin_can_enter_scored_result_from_accepted_document(self):
        User = get_user_model()
        admin = User.objects.create_superuser(
            username="health-owner-admin", email="admin@example.test", password="abc123xyz",
        )
        accepted = Submission.objects.create(
            kind=Submission.Kind.DOCUMENT, status=Submission.Status.APPROVED,
            dog=self.dog, submitted_by=self.owner,
            payload={"document_type": DogDocument.DocumentType.HEALTH},
        )
        evidence = DogDocument.objects.create(
            dog=self.dog, title="Accepted hip report",
            document_type=DogDocument.DocumentType.HEALTH,
            file="documents/accepted-hip-evidence.pdf", source_submission=accepted,
            submitted_by=self.owner,
        )
        self.client.force_login(admin)
        url = reverse("accounts:add-reviewed-health-condition", args=[self.dog.pk])
        self.assertEqual(self.client.post(url, {
            "source_document": str(evidence.pk), "test_type": "HD",
            "result": "A", "reviewed": "on",
        }).status_code, 302)
        rec = HealthRecord.objects.get(dog=self.dog, test_type="HD")
        self.assertEqual(rec.result, "A")
        self.assertEqual(rec.verification_state, VerificationState.HEALTH_VERIFIED)
