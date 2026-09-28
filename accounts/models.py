from django.conf import settings
from django.db import models


class Profile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    display_name = models.CharField(max_length=160, blank=True)
    country = models.CharField(max_length=80, blank=True)
    bio = models.TextField(blank=True)

    def __str__(self):
        return self.display_name or self.user.get_username()
