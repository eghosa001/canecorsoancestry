from datetime import date
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from registry.models import (
    Dog,
    Kennel,
    KennelMembership,
    ModerationAudit,
    ModerationRoleAssignment,
    Submission,
    SubmissionEvidence,
    SubmissionReview,
    SubmissionRiskLevel,
    SubmissionVerificationStatus,
    VerificationRule,
)
from registry.permissions import moderation_role
from registry.services import (
    approve_submission,
    request_high_risk_override,
)
from registry.verification import current_findings, verify_submission
from core.media_views import _can_read_media

from .models import PaymentSubmissionLink, SubmissionPayment


class VerificationGovernanceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.member = User.objects.create_user(
            username="verified-kennel-owner",
            email="kennel@example.com",
            password="test-pass-123",
        )
        self.reviewer = User.objects.create_user(
            username="normal-reviewer",
            password="test-pass-123",
        )
        self.senior_one = User.objects.create_user(
            username="senior-one",
            password="test-pass-123",
        )
        self.senior_two = User.objects.create_user(
            username="senior-two",
            password="test-pass-123",
        )
        ModerationRoleAssignment.objects.create(
            user=self.reviewer,
            role=ModerationRoleAssignment.Role.REVIEWER,
        )
        ModerationRoleAssignment.objects.create(
            user=self.senior_one,
            role=ModerationRoleAssignment.Role.SENIOR,
        )
        ModerationRoleAssignment.objects.create(
            user=self.senior_two,
            role=ModerationRoleAssignment.Role.SENIOR,
        )

        self.kennel = Kennel.objects.create(
            name="Verification Kennel",
            slug="verification-kennel",
            verified_at=timezone.now(),
        )
        KennelMembership.objects.create(
            kennel=self.kennel,
            user=self.member,
            role=KennelMembership.Role.OWNER,
        )
        self.sire = Dog.objects.create(
            name="Verified Sire",
            slug="verified-sire",
            sex=Dog.Sex.MALE,
            date_of_birth=date(2020, 1, 1),
            kennel=self.kennel,
            is_public=True,
        )
        self.dam = Dog.objects.create(
            name="Verified Dam",
            slug="verified-dam",
            sex=Dog.Sex.FEMALE,
            date_of_birth=date(2020, 2, 1),
            kennel=self.kennel,
            is_public=True,
        )
        self.payment = SubmissionPayment.objects.create(
            user=self.member,
            kennel=self.kennel,
            package=SubmissionPayment.Package.LITTER,
            dog_count=0,
            amount_kobo=20000,
            reference="CCA-verification-litter",
            status=SubmissionPayment.Status.PAID,
            paid_at=timezone.now(),
        )
        self.litter_submission = Submission.objects.create(
            kind=Submission.Kind.LITTER_CREATE,
            submitted_by=self.member,
            kennel=self.kennel,
            payload={
                "_paid_submission": True,
                "code": "CCA-L-TEST-001",
                "sire_id": str(self.sire.pk),
                "dam_id": str(self.dam.pk),
                "date_of_birth": "2026-03-12",
                "country": "Nigeria",
                "declared_puppy_count": 4,
                "notes": "",
            },
        )
        PaymentSubmissionLink.objects.create(
            payment=self.payment,
            submission=self.litter_submission,
            slot_kind=PaymentSubmissionLink.SlotKind.LITTER,
        )
        verify_submission(self.litter_submission)
        approve_submission(self.litter_submission, self.reviewer)
        self.litter_submission.refresh_from_db()

    def _puppy_submission(self, *, dob="2024-01-05", name="Dog C"):
        submission = Submission.objects.create(
            kind=Submission.Kind.DOG,
            submitted_by=self.member,
            kennel=self.kennel,
            payload={
                "_paid_submission": True,
                "litter_submission_id": str(self.litter_submission.pk),
                "litter_code": "CCA-L-TEST-001",
                "sire_id": str(self.sire.pk),
                "dam_id": str(self.dam.pk),
                "name": name,
                "sex": Dog.Sex.MALE,
                "date_of_birth": dob,
                "country": "Nigeria",
                "registration": "",
                "microchip_number": "",
                "bio": "",
            },
        )
        PaymentSubmissionLink.objects.create(
            payment=self.payment,
            submission=submission,
            slot_kind=PaymentSubmissionLink.SlotKind.PUPPY,
        )
        verify_submission(submission)
        submission.refresh_from_db()
        return submission

    def test_litter_dob_mismatch_is_explained_and_not_auto_rejected(self):
        submission = self._puppy_submission()

        self.assertEqual(submission.status, Submission.Status.PENDING)
        self.assertEqual(submission.risk_level, SubmissionRiskLevel.RED)
        self.assertEqual(
            submission.verification_status,
            SubmissionVerificationStatus.REVIEW,
        )
        finding = current_findings(submission).get(code="litter_dob_conflict")
        self.assertEqual(finding.expected_value, "2026-03-12")
        self.assertEqual(finding.submitted_value, "2024-01-05")
        self.assertIn("does not match", finding.message)

    def test_flagged_submission_cannot_use_normal_approval(self):
        submission = self._puppy_submission()
        with self.assertRaisesRegex(ValueError, "Approve with override"):
            approve_submission(submission, self.reviewer)

        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.PENDING)
        self.assertFalse(Dog.objects.filter(name="Dog C").exists())

    def test_high_risk_override_requires_different_second_reviewer(self):
        submission = self._puppy_submission()
        first_review = request_high_risk_override(
            submission,
            self.senior_one,
            "Registration certificate supports this litter membership; submitted DOB needs correction.",
        )
        submission.refresh_from_db()
        self.assertEqual(
            submission.verification_status,
            SubmissionVerificationStatus.AWAITING_SECOND,
        )

        with self.assertRaisesRegex(ValueError, "different Senior Moderator or Super Admin"):
            approve_submission(
                submission,
                self.senior_one,
                "Attempted self second approval",
                allow_override=True,
                override_review=first_review,
            )

        approve_submission(
            submission,
            self.senior_two,
            "Independently reviewed the evidence and approved the correction to the litter DOB.",
            allow_override=True,
            override_review=first_review,
        )
        submission.refresh_from_db()
        dog = Dog.objects.get(name="Dog C")

        self.assertEqual(submission.status, Submission.Status.APPROVED)
        self.assertIsInstance(dog.pk, uuid.UUID)
        self.assertEqual(dog.litter_id, self.litter_submission.litter_id)
        self.assertEqual(dog.date_of_birth, date(2026, 3, 12))
        self.assertTrue(dog.is_public)
        self.assertTrue(
            submission.review_decisions.filter(
                action=SubmissionReview.Action.SECOND_APPROVED,
                reviewer=self.senior_two,
            ).exists()
        )
        audit = ModerationAudit.objects.filter(
            submission=submission,
            action=ModerationAudit.Action.SUBMISSION_APPROVED,
        ).latest("created_at")
        first_assignment = ModerationRoleAssignment.objects.get(user=self.senior_one)
        second_assignment = ModerationRoleAssignment.objects.get(user=self.senior_two)
        self.assertEqual(
            audit.summary["first_override_reviewer_admin_number"],
            first_assignment.admin_number,
        )
        self.assertEqual(
            audit.summary["second_reviewer_admin_number"],
            second_assignment.admin_number,
        )

    def test_normal_reviewer_cannot_override_red_finding(self):
        submission = self._puppy_submission()
        with self.assertRaisesRegex(ValueError, "Senior Moderator or Super Admin"):
            request_high_risk_override(
                submission,
                self.reviewer,
                "I want to override this warning.",
            )

    def test_published_ancestry_change_is_locked_for_high_risk_review(self):
        dog = Dog.objects.create(
            name="Published Dog",
            slug="published-dog",
            sex=Dog.Sex.FEMALE,
            date_of_birth=date(2025, 1, 1),
            kennel=self.kennel,
            sire=self.sire,
            dam=self.dam,
            is_public=True,
        )
        correction = Submission.objects.create(
            kind=Submission.Kind.CORRECTION,
            submitted_by=self.member,
            dog=dog,
            kennel=self.kennel,
            payload={
                "name": dog.name,
                "sex": dog.sex,
                "date_of_birth": "2025-02-01",
                "sire_id": str(self.sire.pk),
                "dam_id": str(self.dam.pk),
                "litter_id": None,
                "registration": "",
                "microchip_number": "",
            },
        )
        verify_submission(correction)
        correction.refresh_from_db()

        self.assertEqual(correction.risk_level, SubmissionRiskLevel.RED)
        self.assertTrue(
            current_findings(correction).filter(code="locked_ancestry_change").exists()
        )
        with self.assertRaisesRegex(ValueError, "Approve with override"):
            approve_submission(correction, self.reviewer)

    def test_audit_rows_are_append_only(self):
        event = ModerationAudit.objects.create(
            action=ModerationAudit.Action.VERIFICATION,
            actor=self.senior_one,
            summary={"test": True},
            note="Original",
        )
        event.note = "Changed"
        with self.assertRaisesRegex(ValidationError, "append-only"):
            event.save()
        with self.assertRaisesRegex(ValidationError, "append-only"):
            event.delete()

    def test_wrong_package_cannot_be_used_as_litter_entitlement(self):
        payment = SubmissionPayment.objects.create(
            user=self.member,
            kennel=self.kennel,
            package=SubmissionPayment.Package.SINGLE_DOG,
            dog_count=1,
            amount_kobo=50000,
            reference="CCA-wrong-package",
            status=SubmissionPayment.Status.PAID,
            paid_at=timezone.now(),
        )
        submission = Submission.objects.create(
            kind=Submission.Kind.DOG,
            submitted_by=self.member,
            kennel=self.kennel,
            payload={
                "_paid_submission": True,
                "litter_submission_id": str(self.litter_submission.pk),
                "litter_code": "CCA-L-TEST-001",
                "sire_id": str(self.sire.pk),
                "dam_id": str(self.dam.pk),
                "name": "Wrong Package Puppy",
                "sex": Dog.Sex.FEMALE,
                "date_of_birth": "2026-03-12",
            },
        )
        PaymentSubmissionLink.objects.create(
            payment=payment,
            submission=submission,
            slot_kind=PaymentSubmissionLink.SlotKind.PUPPY,
        )
        verify_submission(submission)
        submission.refresh_from_db()

        self.assertEqual(submission.risk_level, SubmissionRiskLevel.RED)
        self.assertTrue(
            current_findings(submission).filter(code="payment_entitlement").exists()
        )
        self.assertEqual(submission.status, Submission.Status.PENDING)


    def test_green_configured_finding_does_not_block_clean_review(self):
        rule = VerificationRule.objects.get(code="litter_dob_conflict")
        rule.risk_level = SubmissionRiskLevel.GREEN
        rule.second_approval_required = False
        rule.save()

        submission = self._puppy_submission(
            dob="2024-01-05",
            name="Configured Green Puppy",
        )
        self.assertEqual(submission.risk_level, SubmissionRiskLevel.GREEN)
        self.assertEqual(
            submission.verification_status,
            SubmissionVerificationStatus.PASS,
        )

        approve_submission(submission, self.reviewer)
        submission.refresh_from_db()
        dog = Dog.objects.get(name="Configured Green Puppy")
        self.assertEqual(submission.status, Submission.Status.APPROVED)
        self.assertEqual(dog.date_of_birth, date(2026, 3, 12))

    def test_explicit_record_lock_requires_high_risk_review_for_any_correction(self):
        dog = Dog.objects.create(
            name="Locked Dog",
            slug="locked-dog",
            sex=Dog.Sex.MALE,
            date_of_birth=date(2025, 2, 1),
            colour="Black",
            kennel=self.kennel,
            sire=self.sire,
            dam=self.dam,
            is_public=True,
            is_record_locked=True,
            record_locked_at=timezone.now(),
            record_locked_by=self.senior_one,
        )
        correction = Submission.objects.create(
            kind=Submission.Kind.CORRECTION,
            submitted_by=self.member,
            dog=dog,
            kennel=self.kennel,
            payload={
                "name": dog.name,
                "sex": dog.sex,
                "date_of_birth": dog.date_of_birth.isoformat(),
                "colour": "Grey",
                "country": dog.country,
                "bloodline": dog.bloodline,
                "sire_id": str(self.sire.pk),
                "dam_id": str(self.dam.pk),
                "litter_id": None,
                "registration": "",
                "microchip_number": "",
                "bio": dog.bio,
            },
        )
        verify_submission(correction)
        correction.refresh_from_db()

        self.assertEqual(correction.risk_level, SubmissionRiskLevel.RED)
        finding = current_findings(correction).filter(
            code="locked_ancestry_change",
            metadata__record_locked=True,
        ).first()
        self.assertIsNotNone(finding)
        self.assertIn("explicitly locked", finding.message)

    def test_puppy_cannot_borrow_a_different_paid_litter_package(self):
        second_payment = SubmissionPayment.objects.create(
            user=self.member,
            kennel=self.kennel,
            package=SubmissionPayment.Package.LITTER,
            dog_count=0,
            amount_kobo=20000,
            reference="CCA-other-litter-package",
            status=SubmissionPayment.Status.PAID,
            paid_at=timezone.now(),
        )
        submission = Submission.objects.create(
            kind=Submission.Kind.DOG,
            submitted_by=self.member,
            kennel=self.kennel,
            payload={
                "_paid_submission": True,
                "litter_submission_id": str(self.litter_submission.pk),
                "litter_code": "CCA-L-TEST-001",
                "sire_id": str(self.sire.pk),
                "dam_id": str(self.dam.pk),
                "name": "Borrowed Package Puppy",
                "sex": Dog.Sex.FEMALE,
                "date_of_birth": "2026-03-12",
            },
        )
        PaymentSubmissionLink.objects.create(
            payment=second_payment,
            submission=submission,
            slot_kind=PaymentSubmissionLink.SlotKind.PUPPY,
        )
        verify_submission(submission)
        submission.refresh_from_db()

        finding = current_findings(submission).filter(
            code="payment_entitlement"
        ).first()
        self.assertIsNotNone(finding)
        self.assertIn("different paid packages", finding.message)
        self.assertEqual(submission.risk_level, SubmissionRiskLevel.RED)

    def test_moderators_receive_stable_public_admin_numbers(self):
        moderation_role(self.reviewer)
        reviewer_assignment = ModerationRoleAssignment.objects.get(user=self.reviewer)
        senior_assignment = ModerationRoleAssignment.objects.get(user=self.senior_one)

        self.assertGreaterEqual(reviewer_assignment.admin_number, 10001)
        self.assertGreaterEqual(senior_assignment.admin_number, 10001)
        self.assertNotEqual(
            reviewer_assignment.admin_number,
            senior_assignment.admin_number,
        )
        self.assertEqual(
            reviewer_assignment.public_label,
            f"Admin #{reviewer_assignment.admin_number}",
        )

    def test_review_and_audit_snapshot_public_admin_number(self):
        submission = self._puppy_submission(dob="2026-03-12", name="Admin ID Puppy")
        approve_submission(submission, self.reviewer)

        review = submission.review_decisions.latest("created_at")
        audit = submission.audit_events.filter(
            action=ModerationAudit.Action.SUBMISSION_APPROVED
        ).latest("created_at")
        assignment = ModerationRoleAssignment.objects.get(user=self.reviewer)

        self.assertEqual(
            review.reviewer_admin_number_snapshot,
            assignment.admin_number,
        )
        self.assertEqual(
            review.reviewer_admin_label,
            f"Admin #{assignment.admin_number}",
        )
        self.assertEqual(
            audit.actor_admin_number_snapshot,
            assignment.admin_number,
        )
        self.assertEqual(
            audit.actor_admin_label,
            f"Admin #{assignment.admin_number}",
        )

    def test_review_page_uses_admin_id_not_reviewer_username(self):
        submission = self._puppy_submission(dob="2026-03-12", name="Rendered Admin ID Puppy")
        approve_submission(submission, self.reviewer)
        assignment = ModerationRoleAssignment.objects.get(user=self.reviewer)

        self.client.force_login(self.senior_one)
        response = self.client.get(
            reverse("accounts:moderation-submission", args=[submission.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"Admin #{assignment.admin_number}")
        self.assertNotContains(response, self.reviewer.username)

    def test_private_verification_evidence_is_not_public_media(self):
        submission = self._puppy_submission(dob="2026-03-12", name="Evidence Puppy")
        evidence = SubmissionEvidence.objects.create(
            submission=submission,
            evidence_type=SubmissionEvidence.EvidenceType.REGISTRATION,
            file="verification-private/test-certificate.pdf",
            uploaded_by=self.member,
            sha256="a" * 64,
        )

        self.assertEqual(
            _can_read_media(AnonymousUser(), evidence.file.name),
            (False, False),
        )
        self.assertEqual(
            _can_read_media(self.member, evidence.file.name),
            (True, False),
        )
        self.assertEqual(
            _can_read_media(self.reviewer, evidence.file.name),
            (True, False),
        )
