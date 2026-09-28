from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from registry.models import (
    Dog,
    DogDocument,
    Kennel,
    KennelMembership,
    Litter,
    Submission,
)
from registry.services import approve_submission


class KennelClaimTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="claimant", password="test-pass-123"
        )
        self.reviewer = get_user_model().objects.create_user(
            username="claim-reviewer", is_staff=True
        )
        self.kennel = Kennel.objects.create(name="Unlinked Kennel", slug="unlinked-kennel")

    def test_claim_requires_review_then_grants_owner_membership(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:claim-kennel", args=[self.kennel.pk]),
            {"relationship": "Breeder and kennel owner", "notes": "Evidence available."},
        )
        self.assertEqual(response.status_code, 302)

        submission = Submission.objects.get(
            kind=Submission.Kind.KENNEL_CLAIM,
            submitted_by=self.user,
            kennel=self.kennel,
        )
        self.assertFalse(
            KennelMembership.objects.filter(user=self.user, kennel=self.kennel).exists()
        )

        approve_submission(submission, self.reviewer)

        membership = KennelMembership.objects.get(
            user=self.user, kennel=self.kennel
        )
        self.assertEqual(membership.role, KennelMembership.Role.OWNER)

    def test_linked_kennel_cannot_be_claimed_through_public_flow(self):
        existing = get_user_model().objects.create_user(username="existing-owner")
        KennelMembership.objects.create(
            user=existing,
            kennel=self.kennel,
            role=KennelMembership.Role.OWNER,
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("accounts:claim-kennel", args=[self.kennel.pk])
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            Submission.objects.filter(
                submitted_by=self.user, kind=Submission.Kind.KENNEL_CLAIM
            ).exists()
        )


class MemberPedigreeWorkspaceTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            username="pedigree-owner", password="test-pass-123"
        )
        self.outsider = get_user_model().objects.create_user(
            username="pedigree-outsider", password="test-pass-123"
        )
        self.kennel = Kennel.objects.create(name="Private Kennel", slug="private-kennel")
        KennelMembership.objects.create(
            user=self.owner,
            kennel=self.kennel,
            role=KennelMembership.Role.OWNER,
        )
        parent = Dog.objects.create(
            name="Private Parent",
            slug="private-parent",
            kennel=self.kennel,
            sex=Dog.Sex.MALE,
            is_public=False,
        )
        self.dog = Dog.objects.create(
            name="Private Dog",
            slug="private-dog",
            kennel=self.kennel,
            sire=parent,
            is_public=False,
        )

    def test_owner_can_view_private_member_pedigree(self):
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse("accounts:member-pedigree", args=[self.dog.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Private Dog")
        self.assertContains(response, "Private Parent")

    def test_outsider_cannot_view_private_member_pedigree(self):
        self.client.force_login(self.outsider)

        response = self.client.get(
            reverse("accounts:member-pedigree", args=[self.dog.pk])
        )

        self.assertEqual(response.status_code, 404)


class LitterWorkflowTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            username="litter-owner", password="test-pass-123"
        )
        self.reviewer = get_user_model().objects.create_user(
            username="litter-reviewer", is_staff=True
        )
        self.kennel = Kennel.objects.create(name="Litter Kennel", slug="litter-kennel")
        KennelMembership.objects.create(
            user=self.owner,
            kennel=self.kennel,
            role=KennelMembership.Role.OWNER,
        )
        self.sire = Dog.objects.create(
            name="Litter Sire",
            slug="litter-sire",
            sex=Dog.Sex.MALE,
            kennel=self.kennel,
        )
        self.dam = Dog.objects.create(
            name="Litter Dam",
            slug="litter-dam",
            sex=Dog.Sex.FEMALE,
            kennel=self.kennel,
        )

    def test_new_litter_is_moderated_and_starts_private(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("accounts:submit-litter"),
            {
                "code": "A-2026",
                "kennel": str(self.kennel.pk),
                "sire": str(self.sire.pk),
                "dam": str(self.dam.pk),
                "date_of_birth": "2026-09-01",
                "notes": "First litter.",
                "review_notes": "Please review pedigree.",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Litter.objects.filter(code="A-2026").exists())

        submission = Submission.objects.get(kind=Submission.Kind.LITTER_CREATE)
        approve_submission(submission, self.reviewer)

        litter = Litter.objects.get(code="A-2026")
        self.assertFalse(litter.is_public)
        self.assertEqual(litter.sire, self.sire)
        self.assertEqual(litter.dam, self.dam)
        submission.refresh_from_db()
        self.assertEqual(submission.litter, litter)

    def test_litter_edit_waits_for_review(self):
        litter = Litter.objects.create(
            code="OLD-2026",
            kennel=self.kennel,
            sire=self.sire,
            dam=self.dam,
            notes="Old note",
        )
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("accounts:edit-litter", args=[litter.pk]),
            {
                "code": "NEW-2026",
                "kennel": str(self.kennel.pk),
                "sire": str(self.sire.pk),
                "dam": str(self.dam.pk),
                "notes": "Updated note",
            },
        )
        self.assertEqual(response.status_code, 302)
        litter.refresh_from_db()
        self.assertEqual(litter.code, "OLD-2026")

        submission = Submission.objects.get(kind=Submission.Kind.LITTER_EDIT)
        approve_submission(submission, self.reviewer)
        litter.refresh_from_db()
        self.assertEqual(litter.code, "NEW-2026")
        self.assertEqual(litter.notes, "Updated note")

    def test_approved_dog_submission_can_link_to_same_kennel_litter(self):
        litter = Litter.objects.create(
            code="PUP-2026",
            kennel=self.kennel,
            sire=self.sire,
            dam=self.dam,
        )
        submission = Submission.objects.create(
            kind=Submission.Kind.DOG,
            submitted_by=self.owner,
            kennel=self.kennel,
            payload={
                "name": "Litter Puppy",
                "sex": Dog.Sex.MALE,
                "litter_id": str(litter.pk),
            },
        )

        approve_submission(submission, self.reviewer)
        submission.refresh_from_db()

        self.assertEqual(submission.dog.litter, litter)


class DocumentVisibilityTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            username="document-owner", password="test-pass-123"
        )
        self.reviewer = get_user_model().objects.create_user(
            username="document-reviewer", is_staff=True
        )
        self.kennel = Kennel.objects.create(name="Document Kennel", slug="document-kennel")
        KennelMembership.objects.create(
            user=self.owner,
            kennel=self.kennel,
            role=KennelMembership.Role.OWNER,
        )
        dog = Dog.objects.create(
            name="Document Dog",
            slug="document-dog",
            kennel=self.kennel,
        )
        self.document = DogDocument.objects.create(
            dog=dog,
            title="Pedigree evidence",
            document_type=DogDocument.DocumentType.PEDIGREE,
            file="documents/test.pdf",
            is_public=False,
            submitted_by=self.owner,
        )

    def test_document_visibility_change_is_moderated(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("accounts:document-visibility", args=[self.document.pk]),
            {"is_public": "on", "notes": "Publish evidence."},
        )
        self.assertEqual(response.status_code, 302)
        self.document.refresh_from_db()
        self.assertFalse(self.document.is_public)

        submission = Submission.objects.get(
            kind=Submission.Kind.DOCUMENT_VISIBILITY,
            document=self.document,
        )
        approve_submission(submission, self.reviewer)
        self.document.refresh_from_db()
        self.assertTrue(self.document.is_public)


class OptionalEmailNotificationTests(TestCase):
    @override_settings(
        ANCESTRY_EMAIL_NOTIFICATIONS=True,
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="noreply@canecorsoancestry.com",
    )
    def test_review_sends_email_when_feature_is_enabled(self):
        user = get_user_model().objects.create_user(
            username="mail-member",
            email="member@example.com",
        )
        reviewer = get_user_model().objects.create_user(
            username="mail-reviewer", is_staff=True
        )
        kennel = Kennel.objects.create(name="Mail Kennel", slug="mail-kennel")
        submission = Submission.objects.create(
            kind=Submission.Kind.DOG,
            submitted_by=user,
            kennel=kennel,
            payload={"name": "Mail Dog", "sex": Dog.Sex.UNKNOWN},
        )

        approve_submission(submission, reviewer)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("approved", mail.outbox[0].subject.lower())
        self.assertEqual(mail.outbox[0].to, ["member@example.com"])
