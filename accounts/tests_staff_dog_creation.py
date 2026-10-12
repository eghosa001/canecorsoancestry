"""Short, change-scoped checks for private dog creation and staff access governance."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from registry.models import Dog, ModerationAudit, ModerationRoleAssignment
from registry.permissions import can_add_canonical_dog


class StaffDogCreationAndAccessTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_superuser(
            username="staff-owner", email="staff-owner@example.com", password="Owner-pass-123"
        )
        self.senior = User.objects.create_user(
            username="staff-senior", email="staff-senior@example.com", password="Senior-pass-123"
        )
        self.reviewer = User.objects.create_user(
            username="staff-reviewer", email="staff-reviewer@example.com", password="Reviewer-pass-123"
        )
        self.member = User.objects.create_user(username="staff-member", password="Member-pass-123")
        for person, role in (
            (self.owner, ModerationRoleAssignment.Role.OWNER),
            (self.senior, ModerationRoleAssignment.Role.SENIOR),
            (self.reviewer, ModerationRoleAssignment.Role.REVIEWER),
        ):
            ModerationRoleAssignment.objects.create(user=person, role=role, assigned_by=self.owner)

    def test_senior_can_create_unpublished_canonical_dog_with_audit(self):
        self.client.force_login(self.senior)
        url = reverse("accounts:dog-direct-create")
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Add private dog")
        self.assertNotContains(page, 'name="verification_state"')

        result = self.client.post(url, {
            "name": "Record di Aurora",
            "sex": "female",
            "reason": "Official pedigree record checked against breeder evidence",
            "is_public": "on",
            "verification_state": "verified",
        })
        dog = Dog.objects.get(name="Record di Aurora")
        self.assertRedirects(
            result, reverse("accounts:dog-direct-edit", args=[dog.pk]),
            fetch_redirect_response=False,
        )
        self.assertFalse(dog.is_public)
        self.assertEqual(dog.verification_state, "community")
        event = ModerationAudit.objects.get(summary__kind="direct_dog_create")
        self.assertEqual(event.actor, self.senior)
        self.assertEqual(event.dog, dog)
        self.assertFalse(event.summary["is_owner"])

    def test_owner_can_create_private_dog_and_manage_visibility_later(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("accounts:dog-direct-create"), {
            "name": "Owner Record",
            "sex": "male",
            "reason": "Registry entry reviewed and confirmed by super admin",
        })
        self.assertEqual(response.status_code, 302)
        dog = Dog.objects.get(name="Owner Record")
        self.assertFalse(dog.is_public)
        editor = self.client.get(reverse("accounts:dog-direct-edit", args=[dog.pk]))
        self.assertEqual(editor.status_code, 200)
        self.assertContains(editor, "Visibility")

    def test_normal_moderator_can_add_private_dog_with_audit_and_navigation(self):
        self.client.force_login(self.reviewer)
        url = reverse("accounts:dog-direct-create")
        self.assertTrue(can_add_canonical_dog(self.reviewer))
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Add private dog")
        self.assertContains(page, "Moderator / Senior Moderator / Super Admin")
        self.assertNotContains(page, 'name="verification_state"')
        self.assertContains(
            self.client.get(reverse("accounts:dog-edit-list")),
            'href="' + url + '"',
        )
        response = self.client.post(url, {
            "name": "Moderator Created Dog",
            "sex": "female",
            "reason": "Pedigree and breeding kennel evidence reviewed",
            "is_public": "on",
            "verification_state": "verified",
        })
        dog = Dog.objects.get(name="Moderator Created Dog")
        self.assertRedirects(
            response, reverse("accounts:dog-direct-edit", args=[dog.pk]),
            fetch_redirect_response=False,
        )
        self.assertFalse(dog.is_public)
        self.assertEqual(dog.verification_state, "community")
        event = ModerationAudit.objects.get(
            dog=dog, summary__kind="direct_dog_create",
        )
        self.assertEqual(event.actor, self.reviewer)
        self.assertFalse(event.summary["is_owner"])

    def test_member_cannot_add_even_with_forged_post(self):
        url = reverse("accounts:dog-direct-create")
        self.client.force_login(self.member)
        self.assertFalse(can_add_canonical_dog(self.member))
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, {
            "name": "Forbidden record", "sex": "male",
            "reason": "Should never be inserted in the canonical table",
        }).status_code, 403)
        self.assertFalse(Dog.objects.filter(name="Forbidden record").exists())

    def test_deactivated_moderator_cannot_add_dog(self):
        self.reviewer.is_active = False
        self.reviewer.save(update_fields=["is_active"])
        self.assertFalse(can_add_canonical_dog(self.reviewer))
        self.client.force_login(self.reviewer)
        # Django refuses authentication by inactive accounts.
        self.assertEqual(
            self.client.get(reverse("accounts:dog-direct-create")).status_code, 302
        )

    def test_superadmin_dashboard_has_explicit_staff_selector(self):
        self.client.force_login(self.owner)
        page = self.client.get(reverse("accounts:verification-dashboard"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Suspend or reactivate a specific moderator")
        self.assertContains(page, 'id="staff-access-form"')
        self.assertContains(page, 'id="staff-action"')
        markup = page.content.decode()
        selector = markup.split('id="staff-target"', 1)[1].split("</select>", 1)[0]
        self.assertIn(f'<option value="{self.reviewer.pk}">', selector)
        self.assertIn(f'<option value="{self.senior.pk}">', selector)
        self.assertNotIn(f'<option value="{self.owner.pk}">', selector)
        self.assertIn("Choose a moderator account", selector)
        self.assertIn("staff-access.js", markup)
        self.assertIn("staff-access.css", markup)

    def test_superadmin_can_target_one_moderator_without_affecting_others(self):
        self.client.force_login(self.owner)
        url = reverse("accounts:moderation-set-status")
        result = self.client.post(url, {
            "user_id": str(self.reviewer.pk),
            "action": "deactivate",
            "reason": "Scheduled temporary access suspension",
        }, follow=True)
        self.assertEqual(result.status_code, 200)
        self.assertContains(result, "staff-reviewer deactivated")
        self.reviewer.refresh_from_db()
        self.senior.refresh_from_db()
        self.assertFalse(self.reviewer.is_active)
        self.assertTrue(self.senior.is_active)
        self.assertTrue(self.owner.is_active)
        self.assertContains(result, "Deactivated")
        self.assertTrue(ModerationAudit.objects.filter(
            summary__type="moderation_account_deactivated",
            summary__target_admin_number=self.reviewer.ancestry_moderation_role.admin_number,
        ).exists())

        result = self.client.post(url, {
            "user_id": str(self.reviewer.pk),
            "action": "activate",
            "reason": "Suspension review completed",
        }, follow=True)
        self.assertContains(result, "staff-reviewer reactivated")
        self.reviewer.refresh_from_db()
        self.assertTrue(self.reviewer.is_active)
        self.assertTrue(self.senior.is_active)

    def test_staff_selector_cannot_deactivate_superadmin_or_member(self):
        self.client.force_login(self.owner)
        endpoint = reverse("accounts:moderation-set-status")
        for person in (self.owner, self.member):
            result = self.client.post(endpoint, {
                "user_id": str(person.pk),
                "action": "deactivate",
                "reason": "Should be refused safely",
            })
            self.assertEqual(result.status_code, 403)
            person.refresh_from_db()
            self.assertTrue(person.is_active)

    def test_owner_can_deactivate_and_reactivate_senior(self):
        self.client.force_login(self.owner)
        endpoint = reverse("accounts:moderation-set-status")
        self.client.post(endpoint, {
            "user_id": self.senior.pk,
            "action": "deactivate",
            "reason": "Temporary security review",
        })
        self.senior.refresh_from_db()
        self.assertFalse(self.senior.is_active)
        self.assertFalse(can_add_canonical_dog(self.senior))
        self.client.post(endpoint, {
            "user_id": self.senior.pk,
            "action": "activate",
            "reason": "Security review resolved",
        })
        self.senior.refresh_from_db()
        self.assertTrue(self.senior.is_active)
        self.assertTrue(can_add_canonical_dog(self.senior))

    def test_senior_cannot_manage_staff_or_deregister_admin(self):
        self.client.force_login(self.senior)
        for name, data in (
            ("accounts:moderation-set-status", {
                "user_id": self.reviewer.pk, "action": "deactivate", "reason": "Unauthorized",
            }),
            ("accounts:moderation-deregister-staff", {
                "user_id": self.owner.pk, "confirmation": "DEREGISTER",
                "reason": "Unauthorized removal attempt",
            }),
        ):
            self.assertEqual(self.client.post(reverse(name), data).status_code, 403)
        self.reviewer.refresh_from_db()
        self.assertTrue(self.reviewer.is_active)

    def test_deregistration_revokes_identity_without_destroying_evidence(self):
        admin_number = self.senior.ancestry_moderation_role.admin_number
        self.client.force_login(self.owner)
        url = reverse("accounts:moderation-deregister-staff")
        self.client.post(url, {
            "user_id": self.senior.pk,
            "confirmation": "DEREGISTER",
            "reason": "Documented deliberate fraudulent registry entries",
        })
        self.senior.refresh_from_db()
        assignment = self.senior.ancestry_moderation_role
        self.assertFalse(self.senior.is_active)
        self.assertFalse(self.senior.has_usable_password())
        self.assertEqual(self.senior.email, "")
        self.assertTrue(self.senior.username.startswith("removed-admin-"))
        self.assertTrue(assignment.is_deregistered)
        self.assertEqual(assignment.role, ModerationRoleAssignment.Role.NONE)
        self.assertEqual(assignment.admin_number, admin_number)
        self.assertFalse(can_add_canonical_dog(self.senior))
        self.assertTrue(ModerationAudit.objects.filter(
            summary__type="moderation_account_deregistered",
            summary__target_admin_number=admin_number,
        ).exists())
        self.client.post(reverse("accounts:moderation-set-role"), {
            "user_id": self.senior.pk, "role": ModerationRoleAssignment.Role.SENIOR,
        })
        assignment.refresh_from_db()
        self.assertTrue(assignment.is_deregistered)
        page = self.client.get(reverse("accounts:verification-dashboard"))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, self.senior.username)

    def test_cannot_deregister_super_admin(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("accounts:moderation-deregister-staff"), {
            "user_id": self.owner.pk, "confirmation": "DEREGISTER",
            "reason": "Unauthorized super admin removal attempt",
        })
        self.assertEqual(response.status_code, 403)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_active)
