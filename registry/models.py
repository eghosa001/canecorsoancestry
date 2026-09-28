import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class VerificationState(models.TextChoices):
    COMMUNITY = "community", "Community submitted"
    SOURCE_ATTACHED = "source", "Source attached"
    IDENTITY_REVIEWED = "identity", "Identity reviewed"
    PEDIGREE_REVIEWED = "pedigree", "Pedigree reviewed"
    HEALTH_VERIFIED = "health", "Health/DNA verified"


class Kennel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=180)
    slug = models.SlugField(max_length=190, unique=True)
    country = models.CharField(max_length=80, blank=True)
    city = models.CharField(max_length=120, blank=True)
    description = models.TextField(blank=True)
    website = models.URLField(blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class KennelMembership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        EDITOR = "editor", "Editor"
        CONTRIBUTOR = "contributor", "Contributor"

    kennel = models.ForeignKey(Kennel, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="kennel_memberships",
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CONTRIBUTOR)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("kennel", "user"), name="unique_kennel_member")
        ]


class Dog(models.Model):
    class Sex(models.TextChoices):
        MALE = "male", "Male"
        FEMALE = "female", "Female"
        UNKNOWN = "unknown", "Unknown"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=220, db_index=True)
    slug = models.SlugField(max_length=230, unique=True)
    sex = models.CharField(max_length=10, choices=Sex.choices, default=Sex.UNKNOWN)
    date_of_birth = models.DateField(null=True, blank=True)
    colour = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=80, blank=True)
    bloodline = models.CharField(max_length=220, blank=True)
    kennel = models.ForeignKey(
        Kennel,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="dogs",
    )
    sire = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sired_offspring",
    )
    dam = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="dammed_offspring",
    )
    litter = models.ForeignKey(
        "Litter",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="offspring",
    )
    bio = models.TextField(blank=True)
    verification_state = models.CharField(
        max_length=20,
        choices=VerificationState.choices,
        default=VerificationState.COMMUNITY,
        db_index=True,
    )
    is_public = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)
        indexes = [models.Index(fields=("is_public", "verification_state"))]

    def clean(self):
        super().clean()
        if self.pk and self.sire_id == self.pk:
            raise ValidationError({"sire": "A dog cannot be its own sire."})
        if self.pk and self.dam_id == self.pk:
            raise ValidationError({"dam": "A dog cannot be its own dam."})

    def __str__(self):
        return self.name


class Litter(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=80, unique=True)
    kennel = models.ForeignKey(
        Kennel,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="litters",
    )
    sire = models.ForeignKey(
        Dog,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sired_litters",
    )
    dam = models.ForeignKey(
        Dog,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="dammed_litters",
    )
    date_of_birth = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    is_public = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-date_of_birth", "code")

    def __str__(self):
        return self.code


class DogAlias(models.Model):
    dog = models.ForeignKey(Dog, on_delete=models.CASCADE, related_name="aliases")
    name = models.CharField(max_length=220)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("dog", "name"), name="unique_dog_alias")
        ]

    def __str__(self):
        return self.name


class DogExternalKey(models.Model):
    dog = models.ForeignKey(Dog, on_delete=models.CASCADE, related_name="external_keys")
    namespace = models.CharField(max_length=80)
    key = models.CharField(max_length=230)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("namespace", "key"),
                name="unique_external_dog_key",
            )
        ]

    def __str__(self):
        return f"{self.namespace}:{self.key}"


class RegistrationAuthority(models.Model):
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=180, unique=True)
    country = models.CharField(max_length=80, blank=True)

    class Meta:
        verbose_name_plural = "registration authorities"
        ordering = ("code",)

    def __str__(self):
        return self.code


class DogRegistration(models.Model):
    dog = models.ForeignKey(Dog, on_delete=models.CASCADE, related_name="registrations")
    authority = models.ForeignKey(
        RegistrationAuthority,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="registrations",
    )
    number = models.CharField(max_length=120)
    issued_on = models.DateField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("authority", "number"),
                name="unique_registration_number_per_authority",
            ),
            models.UniqueConstraint(
                fields=("number",),
                condition=Q(authority__isnull=True),
                name="unique_registration_number_without_authority",
            ),
        ]

    def __str__(self):
        if self.authority:
            return f"{self.authority.code} {self.number}"
        return self.number


class DogImage(models.Model):
    dog = models.ForeignKey(Dog, on_delete=models.CASCADE, related_name="images")
    image = models.FileField(upload_to="dogs/%Y/%m/")
    caption = models.CharField(max_length=220, blank=True)
    is_primary = models.BooleanField(default=False)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("sort_order", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("dog",),
                condition=Q(is_primary=True),
                name="one_primary_image_per_dog",
            )
        ]


class DogTitle(models.Model):
    dog = models.ForeignKey(Dog, on_delete=models.CASCADE, related_name="titles")
    name = models.CharField(max_length=160)
    source_text = models.CharField(max_length=220, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(fields=("dog", "name"), name="unique_dog_title")
        ]

    def __str__(self):
        return self.name


class HealthRecord(models.Model):
    dog = models.ForeignKey(Dog, on_delete=models.CASCADE, related_name="health_records")
    test_type = models.CharField(max_length=100)
    result = models.CharField(max_length=160)
    tested_on = models.DateField(null=True, blank=True)
    verification_state = models.CharField(
        max_length=20,
        choices=VerificationState.choices,
        default=VerificationState.COMMUNITY,
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("test_type", "-tested_on")


class DogSource(models.Model):
    class SourceType(models.TextChoices):
        PEDIGREE = "pedigree", "Pedigree document"
        REGISTRY = "registry", "Registry record"
        HEALTH = "health", "Health/DNA document"
        BREEDER = "breeder", "Breeder supplied"
        OTHER = "other", "Other"

    dog = models.ForeignKey(Dog, on_delete=models.CASCADE, related_name="sources")
    source_type = models.CharField(max_length=20, choices=SourceType.choices)
    title = models.CharField(max_length=220)
    source_url = models.URLField(blank=True)
    document = models.FileField(upload_to="evidence/%Y/%m/", blank=True)
    notes = models.TextField(blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
