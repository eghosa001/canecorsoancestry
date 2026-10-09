"""Accessible public and member pedigree navigation without exposing private dogs."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from registry.models import Dog, Kennel, KennelMembership


class PedigreeNavigationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.kennel = Kennel.objects.create(
            name="Research Navigation Kennel", slug="research-navigation-kennel"
        )
        cls.public = Dog.objects.create(
            name="Public Navigation Dog", slug="public-navigation-dog",
            is_public=True, kennel=cls.kennel,
        )
        cls.private = Dog.objects.create(
            name="Private Navigation Dog", slug="private-navigation-dog",
            is_public=False, kennel=cls.kennel,
        )
        User = get_user_model()
        cls.member = User.objects.create_user(username="pedigree-navigation-member")
        cls.other_member = User.objects.create_user(username="pedigree-navigation-other")
        KennelMembership.objects.create(
            user=cls.member, kennel=cls.kennel, role=KennelMembership.Role.OWNER,
        )

    def test_public_pedigree_supports_keyboard_and_back_navigation(self):
        url = reverse("pedigrees:detail", args=[self.public.slug])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-label="Pedigree research navigation"')
        self.assertContains(response, 'role="region" tabindex="0"')
        self.assertContains(response, "Jump to analysis")
        self.assertContains(response, reverse(
            "pedigrees:reverse", args=[self.public.slug]
        ))
        self.assertContains(response, reverse(
            "registry:dog-detail", args=[self.public.slug]
        ))
        self.assertContains(response, "Keyboard users can focus the pedigree tree")

    def test_member_private_tree_remains_access_controlled(self):
        url = reverse("accounts:member-pedigree", args=[self.private.pk])
        self.client.force_login(self.member)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-label="Private pedigree navigation"')
        self.assertContains(response, 'role="region" tabindex="0"')
        self.assertNotContains(
            response, reverse("registry:dog-detail", args=[self.private.slug])
        )
        self.client.force_login(self.other_member)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_unapproved_dog_remains_inaccessible_publicly(self):
        self.assertEqual(
            self.client.get(reverse(
                "pedigrees:detail", args=[self.private.slug]
            )).status_code, 404
        )
