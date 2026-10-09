"""Regression coverage: Super Admin work queue and SQL-bounded reviewer metrics."""
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from registry.models import (
    Dog, ModerationAudit, ModerationRoleAssignment, Submission, SubmissionReview,
)


class OwnerPedigreeInboxTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.owner = User.objects.create_superuser(
            username="quality-owner", email="quality-owner@example.test",
            password="Example-only-123",
        )
        cls.mod = User.objects.create_user(username="quality-reviewer")
        cls.member = User.objects.create_user(username="quality-member")
        ModerationRoleAssignment.objects.create(
            user=cls.owner, role=ModerationRoleAssignment.Role.OWNER,
            assigned_by=cls.owner,
        )
        ModerationRoleAssignment.objects.create(
            user=cls.mod, role=ModerationRoleAssignment.Role.REVIEWER,
            assigned_by=cls.owner,
        )
        cls.dog = Dog.objects.create(
            name="Protected Inbox Dog", slug="protected-inbox-dog",
            sex=Dog.Sex.UNKNOWN, is_public=True,
        )

    def direct_edit_payload(self):
        url = reverse("accounts:dog-direct-edit", args=[self.dog.pk])
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        data = {
            "version": page.context["version"],
            "name": self.dog.name,
            "sex": Dog.Sex.MALE,
            "verification_state": self.dog.verification_state,
            "reason": "Reviewed original breeder parentage record",
        }
        for prefix, formset in page.context["formsets"].items():
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
        return data

    def test_proposal_appears_as_unpublished_for_super_admin(self):
        self.client.force_login(self.mod)
        editor = reverse("accounts:dog-direct-edit", args=[self.dog.pk])
        self.assertEqual(self.client.post(
            editor, self.direct_edit_payload()
        ).status_code, 302)
        proposal = ModerationAudit.objects.get(summary__kind="direct_dog_proposal")
        self.client.force_login(self.owner)
        overview = self.client.get(reverse("accounts:verification-dashboard"))
        self.assertEqual(overview.status_code, 200)
        self.assertContains(overview, "Published pedigree changes awaiting approval")
        self.assertContains(overview, "Protected Inbox Dog")
        self.assertContains(overview, "Awaiting Super Admin")
        self.assertEqual(len(overview.context["pending_proposals"]), 1)
        self.assertContains(
            self.client.get(reverse("accounts:dog-edit-list") + "?proposals=1"),
            "Pending Super Admin approval",
        )
        # Approving changes public data on next GET; queue omits reviewed edits.
        self.assertEqual(self.client.post(
            reverse("accounts:dog-review-edit", args=[self.dog.pk, proposal.pk]),
            {"decision": "approve", "reason": "Verified against breeder's evidence"},
        ).status_code, 302)
        overview = self.client.get(reverse("accounts:verification-dashboard"))
        self.assertEqual(len(overview.context["pending_proposals"]), 0)
        self.assertContains(
            self.client.get(reverse("accounts:dog-edit-list") + "?proposals=1"),
            "Approved and published",
        )
        self.dog.refresh_from_db()
        self.assertEqual(self.dog.sex, Dog.Sex.MALE)

    def test_non_superadmin_has_no_owner_inbox(self):
        for user in (self.member, self.mod):
            self.client.force_login(user)
            self.assertEqual(
                self.client.get(reverse("accounts:verification-dashboard")).status_code,
                403,
            )
        self.client.force_login(self.mod)
        page = self.client.get(reverse("accounts:dog-edit-list") + "?proposals=1")
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "Review protected proposals")

    def test_reviewer_dashboard_metrics_preserve_counts_with_constant_aggregate_query(self):
        submission = Submission.objects.create(
            kind=Submission.Kind.KENNEL_CREATE,
            submitted_by=self.member,
            payload={"name": "Review Test Kennel", "slug": "review-test-kennel"},
        )
        SubmissionReview.objects.create(
            submission=submission, reviewer=self.mod,
            action=SubmissionReview.Action.APPROVED, reason="Clean record",
        )
        SubmissionReview.objects.create(
            submission=submission, reviewer=self.mod,
            action=SubmissionReview.Action.OVERRIDE_REQUESTED,
            reason="Evidence retained", warnings_snapshot=[{"code": "dob"}],
        )
        self.client.force_login(self.owner)
        with CaptureQueriesContext(connection) as statements:
            response = self.client.get(reverse("accounts:verification-dashboard"))
        self.assertEqual(response.status_code, 200)
        row = next(item for item in response.context["reviewer_rows"]
                   if item["user"].pk == self.mod.pk)
        self.assertEqual(row["reviews"], 2)
        self.assertEqual(row["approved"], 1)
        self.assertEqual(row["overrides"], 1)
        self.assertEqual(row["flagged"], 1)
        self.assertEqual(row["override_rate"], 50.0)
        review_aggregate_selects = [
            statement["sql"].lower() for statement in statements
            if "from \"registry_submissionreview\"" in statement["sql"].lower()
            and "group by" in statement["sql"].lower()
        ]
        self.assertEqual(len(review_aggregate_selects), 1)
