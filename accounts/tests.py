from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import Profile


class ProfileTests(TestCase):
    def test_display_name_is_used_for_profile_label(self):
        user = get_user_model().objects.create_user(username="kelvin")
        profile = Profile.objects.create(user=user, display_name="Kelvin Omigie")
        self.assertEqual(str(profile), "Kelvin Omigie")
