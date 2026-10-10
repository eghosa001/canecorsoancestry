"""Regression tests for owner-requested profile, ancestry and image corrections."""
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from registry.models import (
    DisputeCase, Dog, DogDocument, DogImage, DogTitle,
    Kennel, ModerationAudit, ModerationRoleAssignment, Submission,
)
from registry.services import approve_submission, record_audit


class OwnerFeedbackFixesTests(TestCase):
    def setUp(self):
        self.temp_media = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_media.cleanup)
        media_settings = override_settings(
            MEDIA_ROOT=self.temp_media.name, MEDIA_EDGE_BASE_URL="",
        )
        media_settings.enable()
        self.addCleanup(media_settings.disable)
        user = get_user_model()
        self.owner = user.objects.create_superuser(
            username="owner-feedback-owner", email="owner-feedback-owner@example.com",
            password="safe-test-only",
        )
        self.staff = user.objects.create_user(username="owner-feedback-staff")
        self.member = user.objects.create_user(username="owner-feedback-member")
        ModerationRoleAssignment.objects.create(
            user=self.owner, role=ModerationRoleAssignment.Role.OWNER,
            assigned_by=self.owner,
        )
        ModerationRoleAssignment.objects.create(
            user=self.staff, role=ModerationRoleAssignment.Role.REVIEWER,
            assigned_by=self.owner,
        )
        self.kennel = Kennel.objects.create(name="Owner Test Kennel", slug="owner-test-kennel")
        self.dog = Dog.objects.create(
            name="Owner Review Dog", slug="owner-review-dog",
            sex=Dog.Sex.MALE, kennel=self.kennel, is_public=True,
        )

    def test_parent_picker_requires_staff_and_returns_exact_identity(self):
        sire = Dog.objects.create(
            name="Common Parent", slug="owner-sire", sex=Dog.Sex.MALE, is_public=False,
        )
        Dog.objects.create(
            name="Common Parent", slug="owner-dam",
            sex=Dog.Sex.FEMALE, is_public=False,
        )
        url = reverse("accounts:dog-parent-suggestions")
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(url, {"q": "Common", "sex": "male"}).status_code, 403)
        self.client.force_login(self.staff)
        response = self.client.get(url, {"q": "Common", "sex": "male"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()["results"]], [str(sire.pk)])
        self.assertEqual(response.json()["results"][0]["is_public"], False)
        self.assertEqual(self.client.get(url, {"q": "C", "sex": "male"}).json(), {"results": []})

    def test_staff_editor_renders_readable_selected_ancestor_names(self):
        sire = Dog.objects.create(
            name="Verified Sire of Review", slug="verified-sire-of-review",
            sex=Dog.Sex.MALE, is_public=False,
        )
        dam = Dog.objects.create(
            name="Verified Dam of Review", slug="verified-dam-of-review",
            sex=Dog.Sex.FEMALE, is_public=False,
        )
        self.dog.sire = sire
        self.dog.dam = dam
        self.dog.save()
        self.client.force_login(self.staff)
        response = self.client.get(
            reverse("accounts:dog-direct-edit", args=[self.dog.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-current-parent-name="Verified Sire of Review"')
        self.assertContains(response, 'data-current-parent-name="Verified Dam of Review"')
        self.assertContains(response, f'data-current-parent-id="{sire.pk}"')
        self.assertContains(response, f'data-current-parent-id="{dam.pk}"')
        self.assertContains(response, 'data-parent-results-for="sire_ref"')
        self.assertContains(response, 'data-parent-results-for="dam_ref"')

    @patch("registry.services.verify_submission", return_value=[])
    def test_title_certificate_stays_private_until_review(self, _verification):
        sub = Submission.objects.create(
            kind=Submission.Kind.DOCUMENT, submitted_by=self.member,
            dog=self.dog, kennel=self.kennel,
            payload={
                "title": "Champion award proof",
                "document_type": "title_certificate",
                "achievement_title": "National Champion",
                "certificate_issuer": "Example Club",
                "certificate_awarded_on": "2025-05-01",
                "is_public": True,
            },
            attachment=SimpleUploadedFile("award.pdf", b"%PDF-1.4 owner-test"),
        )
        url = reverse("registry:dog-detail", args=[self.dog.slug])
        self.assertNotContains(self.client.get(url), "National Champion")
        with self.captureOnCommitCallbacks(execute=True):
            approve_submission(sub, self.staff, "Certificate checked")
        title = DogTitle.objects.get(dog=self.dog)
        certificate = DogDocument.objects.get(source_submission=sub)
        self.assertEqual(title.name, "National Champion")
        self.assertIn(f"[CCA certificate #{certificate.pk}]", title.source_text)
        self.assertIn("Example Club", certificate.title)
        self.assertContains(self.client.get(url), "View reviewed certificate")

    def test_reported_photo_replacement_changes_only_reviewed_image(self):
        previous = DogImage.objects.create(
            dog=self.dog, image=SimpleUploadedFile(
                "previous.jpg", b"original-photo-data", content_type="image/jpeg",
            ), is_primary=True,
        )
        case = DisputeCase.objects.create(
            dog=self.dog, opened_by=self.member,
            reason=DisputeCase.Reason.IDENTITY,
            details="The published image belongs to a different dog.",
            attachment=SimpleUploadedFile(
                "new-photo.jpg", b"replacement-photo-data", content_type="image/jpeg",
            ),
        )
        record_audit(
            action=ModerationAudit.Action.DISPUTE_OPENED, actor=self.member,
            dog=self.dog, dispute=case,
            summary={"reason": "identity", "report_type": "photo", "target_image_id": previous.pk},
        )
        self.client.force_login(self.staff)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("accounts:review-dispute", args=[case.pk, "replace_photo"]),
                {"resolution_notes": "Verified picture against club records"},
            )
        self.assertEqual(response.status_code, 302)
        case.refresh_from_db()
        self.assertEqual(case.status, DisputeCase.Status.RESOLVED)
        self.assertFalse(DogImage.objects.filter(pk=previous.pk).exists())
        replacement = DogImage.objects.get(dog=self.dog, is_primary=True)
        self.assertIn("new-photo", replacement.image.name)
        self.assertContains(
            self.client.get(reverse("registry:dog-detail", args=[self.dog.slug])),
            replacement.image.url,
        )
        # Closed disputes cannot be replayed to delete a later correction.
        self.client.post(
            reverse("accounts:review-dispute", args=[case.pk, "remove_photo"]),
            {"resolution_notes": "Unexpected replay"},
        )
        self.assertTrue(DogImage.objects.filter(pk=replacement.pk).exists())

    def test_public_review_links_are_members_only_and_target_sections(self):
        url = reverse("registry:dog-detail", args=[self.dog.slug])
        guest = self.client.get(url)
        self.assertNotContains(guest, "Request a detail correction")
        self.assertNotContains(guest, 'href="/member/dogs/')
        self.client.force_login(self.member)
        response = self.client.get(url)
        self.assertContains(response, "Request a detail correction")
        self.assertContains(response, "?field=other")
        self.assertContains(response, "?field=offspring")
        self.assertContains(response, "?reason=health&amp;field=health")
        self.assertContains(response, 'id="profile-details"')
        self.assertContains(response, "profile-report-actions", count=0)

    def test_member_can_report_exact_field_and_moderators_receive_audit(self):
        from accounts.forms import DOG_REVIEW_LABELS
        self.assertTrue({
            "name", "sire", "dam", "sex", "date_of_birth", "colour",
            "bloodline", "country", "kennel", "registration",
            "registration_authority", "coi", "siblings", "offspring", "mates",
            "litter", "health", "dna", "titles", "title_certificate",
            "document", "verification", "source", "biography", "photo", "other",
        } <= set(DOG_REVIEW_LABELS))
        url = reverse("accounts:open-dispute", args=[self.dog.pk])
        self.client.force_login(self.member)
        for target in ("name", "sire", "dam", "coi", "health", "offspring", "title_certificate", "document", "other"):
            with self.subTest(target=target):
                get = self.client.get(url, {"field": target})
                self.assertEqual(get.status_code, 200)
                self.assertEqual(get.context["form"].initial["target_field"], target)
                response = self.client.post(url, {
                    "reason": "pedigree",
                    "target_field": target,
                    "target_entry": "Named source row",
                    "details": "Please check the supporting record.",
                })
                self.assertRedirects(response, reverse("accounts:my-disputes"))
                case = DisputeCase.objects.latest("created_at")
                audit = ModerationAudit.objects.filter(
                    dispute=case, action=ModerationAudit.Action.DISPUTE_OPENED,
                ).get()
                self.assertEqual(audit.summary["target_field"], target)
                self.assertEqual(audit.summary["target_label"], DOG_REVIEW_LABELS[target])
                self.assertEqual(audit.summary["target_entry"], "Named source row")
                self.assertIn(DOG_REVIEW_LABELS[target], case.details)
                self.assertIn("Named source row", case.details)
        self.client.logout()
        guest = self.client.get(url)
        self.assertEqual(guest.status_code, 302)

    def test_member_photo_report_validated_and_never_changes_images_directly(self):
        first_photo = DogImage.objects.create(
            dog=self.dog, image="dogs/report-proof.jpg", is_primary=True,
        )
        url = reverse("accounts:open-dispute", args=[self.dog.pk])
        self.client.force_login(self.member)
        get = self.client.get(url, {"field": "photo"})
        self.assertEqual(get.context["form"].initial["reason"], "photo")
        self.assertEqual(get.context["form"].initial["target_field"], "photo")
        result = self.client.post(url, {
            "reason": "identity",
            "target_field": "photo",
            "target_image": str(first_photo.pk),
            "details": "This is a different animal.",
        })
        self.assertEqual(result.status_code, 302)
        case = DisputeCase.objects.latest("created_at")
        self.assertEqual(case.reason, DisputeCase.Reason.IDENTITY)
        audit = ModerationAudit.objects.filter(dispute=case).get()
        self.assertEqual(audit.summary["report_type"], "photo")
        self.assertEqual(audit.summary["target_field"], "photo")
        self.assertTrue(DogImage.objects.filter(pk=first_photo.pk).exists())
        invalid = self.client.post(url, {
            "reason": "photo",
            "target_field": "dam",
            "details": "Must not combine categories.",
        })
        self.assertEqual(invalid.status_code, 200)
        self.assertIn("target_field", invalid.context["form"].errors)

    def test_new_django_admin_dog_requires_explicit_super_admin_publication(self):
        self.dog.is_public = False
        self.dog.save(update_fields=["is_public"])
        self.assertEqual(
            self.client.get(reverse("registry:dog-detail", args=[self.dog.slug])).status_code,
            404,
        )
        self.client.force_login(self.owner)
        edit_url = reverse("accounts:dog-direct-edit", args=[self.dog.pk])
        publish_url = reverse("accounts:dog-set-public-visibility", args=[self.dog.pk])
        self.assertContains(self.client.get(edit_url), "Publish to website")
        self.assertEqual(self.client.get(publish_url).status_code, 405)
        version = self.dog.updated_at.isoformat()
        before_state = self.dog.verification_state
        response = self.client.post(publish_url, {
            "action": "publish",
            "reason": "Owner reviewed the dog's identity.",
            "confirm_visibility": "yes",
            "version": version,
        })
        self.assertRedirects(response, edit_url)
        self.dog.refresh_from_db()
        self.assertTrue(self.dog.is_public)
        self.assertEqual(self.dog.verification_state, before_state)
        self.assertEqual(
            self.client.get(reverse("registry:dog-detail", args=[self.dog.slug])).status_code,
            200,
        )
        self.assertContains(
            self.client.get(reverse("registry:dog-search"), {"q": self.dog.name}),
            self.dog.name,
        )
        # A published dog without an image must be reachable by search/direct URL
        # but cannot crowd the main visual browse grid with an empty image.
        self.assertNotContains(
            self.client.get(reverse("registry:dog-search")),
            "Owner Review Dog",
        )
        audit = ModerationAudit.objects.get(
            dog=self.dog, action=ModerationAudit.Action.RECORD_CHANGED,
            summary__publication_action="publish",
        )
        self.assertEqual(audit.actor, self.owner)
        self.assertEqual(audit.summary["before"]["publication"]["is_public"], False)
        self.assertEqual(audit.summary["after"]["publication"]["is_public"], True)
        self.assertEqual(audit.note, "Owner reviewed the dog's identity.")
        self.assertContains(self.client.get(edit_url), "Unpublish from website")

    def test_publish_permission_confirmation_concurrency_and_unpublish(self):
        self.dog.is_public = False
        self.dog.save(update_fields=["is_public"])
        url = reverse("accounts:dog-set-public-visibility", args=[self.dog.pk])
        version = self.dog.updated_at.isoformat()
        valid = {
            "action": "publish",
            "confirm_visibility": "yes",
            "reason": "Reviewed dog entry",
            "version": version,
        }
        self.client.force_login(self.member)
        self.assertEqual(self.client.post(url, valid).status_code, 403)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.post(url, valid).status_code, 403)
        self.assertNotContains(
            self.client.get(reverse("accounts:dog-direct-edit", args=[self.dog.pk])),
            "Publish to website",
        )
        self.client.force_login(self.owner)
        self.client.post(url, {**valid, "confirm_visibility": ""})
        self.dog.refresh_from_db()
        self.assertFalse(self.dog.is_public)
        self.client.post(url, {**valid, "reason": "No"})
        self.dog.refresh_from_db()
        self.assertFalse(self.dog.is_public)
        self.dog.bio = "Updated between review and publish"
        self.dog.save(update_fields=["bio", "updated_at"])
        self.client.post(url, valid)
        self.dog.refresh_from_db()
        self.assertFalse(self.dog.is_public)
        self.assertEqual(ModerationAudit.objects.filter(
            dog=self.dog, summary__publication_action="publish",
        ).count(), 0)
        self.client.post(url, {**valid, "version": self.dog.updated_at.isoformat()})
        self.dog.refresh_from_db()
        self.assertTrue(self.dog.is_public)
        self.client.post(url, {
            "action": "unpublish", "reason": "Owner withdrew approval",
            "confirm_visibility": "yes", "version": self.dog.updated_at.isoformat(),
        })
        self.dog.refresh_from_db()
        self.assertFalse(self.dog.is_public)
        self.assertEqual(
            self.client.get(reverse("registry:dog-detail", args=[self.dog.slug])).status_code,
            404,
        )
        self.assertEqual(ModerationAudit.objects.filter(
            dog=self.dog, summary__publication_action="unpublish",
        ).count(), 1)

    def test_django_admin_explains_how_to_publish(self):
        self.dog.is_public = False
        self.dog.save(update_fields=["is_public"])
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("admin:registry_dog_change", args=[self.dog.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Manage publication / make public")
        self.assertContains(response, reverse("accounts:dog-direct-edit", args=[self.dog.pk]))

    def test_photo_case_cannot_be_closed_without_corrective_action(self):
        case = DisputeCase.objects.create(
            dog=self.dog, opened_by=self.member,
            reason=DisputeCase.Reason.IDENTITY,
            details="Incorrect photograph",
        )
        record_audit(
            action=ModerationAudit.Action.DISPUTE_OPENED, actor=self.member,
            dog=self.dog, dispute=case,
            summary={"reason": "identity", "report_type": "photo"},
        )
        self.client.force_login(self.staff)
        self.client.post(
            reverse("accounts:review-dispute", args=[case.pk, "resolve"]),
            {"resolution_notes": "Simply mark done"},
        )
        case.refresh_from_db()
        self.assertEqual(case.status, DisputeCase.Status.OPEN)
