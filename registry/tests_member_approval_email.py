"""Email decisions to the kennel member only after final approval commits."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.db import transaction
from django.test import TestCase, override_settings

from registry.models import (
    Kennel, ModerationRoleAssignment, Notification, Submission,
)
from registry.services import approve_submission, resend_approved_submission_email


@override_settings(
    ACCOUNT_EMAIL_ENABLED=True,
    ANCESTRY_EMAIL_NOTIFICATIONS=False,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    SITE_URL="https://canecorsoancestry.com",
    DEFAULT_FROM_EMAIL="Cane Corso Ancestry <notice@canecorsoancestry.com>",
)
@patch("registry.services.verify_submission", return_value=[])
class MemberApprovalEmailTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.reviewer = User.objects.create_user(username="staff-reviewer")
        ModerationRoleAssignment.objects.create(
            user=self.reviewer,
            role=ModerationRoleAssignment.Role.REVIEWER,
        )
        self.member = User.objects.create_user(
            username="kennel-member",
            email="kennel-member@example.com",
        )
        self.other = User.objects.create_user(
            username="other-member",
            email="other@example.com",
        )
        self.kennel = Kennel.objects.create(
            name="Member-owned Kennel", slug="member-owned-kennel",
        )

    def submission(self, *, kennel=None):
        return Submission.objects.create(
            kind=Submission.Kind.KENNEL,
            submitted_by=self.member,
            kennel=self.kennel if kennel is None else kennel,
            payload={"city": "Benin City"},
        )

    def test_successful_approval_emails_only_the_submitting_member_once(self, _verify):
        submission = self.submission()
        with self.captureOnCommitCallbacks(execute=True):
            approve_submission(submission, self.reviewer)
            self.assertEqual(len(mail.outbox), 0)

        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.APPROVED)
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertEqual(email.to, [self.member.email])
        self.assertIn("Kennel update approved", email.subject)
        self.assertIn(self.kennel.name, email.body)
        self.assertIn(
            "https://canecorsoancestry.com/member/submissions/", email.body,
        )
        self.assertEqual(
            Notification.objects.filter(user=self.member).count(), 1,
        )
        self.assertFalse(Notification.objects.filter(user=self.other).exists())
        with self.assertRaisesRegex(ValueError, "Only pending"):
            approve_submission(submission, self.reviewer)
        self.assertEqual(len(mail.outbox), 1)

    def test_failed_review_does_not_email_or_approve(self, _verify):
        submission = self.submission(kennel=self.kennel)
        submission.kennel = None
        submission.save(update_fields=["kennel"])
        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaisesRegex(ValueError, "no target kennel"):
                approve_submission(submission, self.reviewer)
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.PENDING)
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(Notification.objects.exists())

    def test_rolled_back_approval_never_sends_email(self, _verify):
        submission = self.submission()
        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaisesRegex(RuntimeError, "rollback"):
                with transaction.atomic():
                    approve_submission(submission, self.reviewer)
                    raise RuntimeError("rollback")
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.PENDING)
        self.assertFalse(Notification.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_smtp_failure_is_logged_without_undoing_approval(self, _verify):
        submission = self.submission()
        with patch("registry.services.send_mail", side_effect=OSError("SMTP down")):
            with self.assertLogs("registry.services", level="ERROR") as captured:
                with self.captureOnCommitCallbacks(execute=True):
                    approve_submission(submission, self.reviewer)

        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.APPROVED)
        self.assertTrue(Notification.objects.filter(user=self.member).exists())
        self.assertTrue(any(
            "submission_decision_email_failed" in entry
            for entry in captured.output
        ))

    @override_settings(ACCOUNT_EMAIL_ENABLED=False)
    def test_unconfigured_transport_does_not_send_mail(self, _verify):
        submission = self.submission()
        with self.captureOnCommitCallbacks(execute=True):
            approve_submission(submission, self.reviewer)
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(Notification.objects.filter(user=self.member).exists())

    def test_retry_uses_corrected_account_email_without_reapproving(self, _verify):
        submission = self.submission()
        with self.captureOnCommitCallbacks(execute=True):
            approve_submission(submission, self.reviewer)
        get_user_model().objects.filter(pk=self.member.pk).update(
            email="corrected-member@example.com",
        )
        self.assertTrue(resend_approved_submission_email(submission))
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[-1].to, ["corrected-member@example.com"])
        self.assertEqual(Notification.objects.filter(user=self.member).count(), 1)
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.APPROVED)

    def test_retry_refuses_pending_submission(self, _verify):
        self.assertFalse(resend_approved_submission_email(self.submission()))
        self.assertEqual(len(mail.outbox), 0)

    def test_inactive_account_does_not_receive_decision_email(self, _verify):
        self.member.is_active = False
        self.member.save(update_fields=["is_active"])
        submission = self.submission()
        with self.captureOnCommitCallbacks(execute=True):
            approve_submission(submission, self.reviewer)
        self.assertEqual(len(mail.outbox), 0)
        self.assertTrue(Notification.objects.filter(user=self.member).exists())

    def test_retry_rejects_malformed_address(self, _verify):
        submission = self.submission()
        with self.captureOnCommitCallbacks(execute=True):
            approve_submission(submission, self.reviewer)
        get_user_model().objects.filter(pk=self.member.pk).update(email="invalid")
        self.assertFalse(resend_approved_submission_email(submission))
        self.assertEqual(len(mail.outbox), 1)
