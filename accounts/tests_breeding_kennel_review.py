"""Staff review of historical breeding kennel provenance must remain safe."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from registry.models import Dog, Kennel, ModerationRoleAssignment


class BreedingKennelReviewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.moderator = User.objects.create_user(
            username="breeding-provenance-moderator", password="passA123!"
        )
        ModerationRoleAssignment.objects.create(
            user=self.moderator, role=ModerationRoleAssignment.Role.REVIEWER,
        )
        self.member = User.objects.create_user(username="ordinary-member")
        self.kennel = Kennel.objects.create(
            name="Custodinus", slug="custodinus", is_public=True,
        )
        self.dog = Dog.objects.create(
            name="Agatha Custodinus", slug="agatha-custodinus", is_public=True
        )
        self.other = Dog.objects.create(
            name="No Named Breeder", slug="no-named-breeder", is_public=True
        )

    def url(self):
        return reverse("accounts:kennel-reconciliation-review")

    def test_member_is_forbidden_access_to_private_reconciliation(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(self.url()).status_code, 403)

    def test_moderator_can_review_suggestions_but_no_dog_is_changed(self):
        self.client.force_login(self.moderator)
        response = self.client.get(self.url(), {"q": "Agatha"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Agatha Custodinus")
        self.assertContains(response, "Custodinus")
        self.assertContains(response, "not verified ownership")
        self.assertContains(
            response, "?kennel=" + str(self.kennel.pk)
        )
        self.assertEqual(response.context["page_obj"].paginator.count, 1)
        self.dog.refresh_from_db()
        self.assertIsNone(self.dog.kennel_id)

    def test_page_excludes_already_linked_dogs(self):
        self.dog.kennel = self.kennel
        self.dog.save(update_fields=["kennel"])
        self.client.force_login(self.moderator)
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Agatha Custodinus")
        self.assertContains(response, "No Named Breeder")

    def test_moderation_kennel_directory_links_to_review_queue(self):
        self.client.force_login(self.moderator)
        page = self.client.get(reverse("accounts:kennel-publication-list"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, self.url())
