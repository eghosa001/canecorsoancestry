import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
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


class SubmissionPayment(models.Model):
    class Package(models.TextChoices):
        SINGLE_DOG = "single_dog", "1 dog"
        MULTI_DOG = "multi_dog", "2–6 dogs"
        LITTER = "litter", "1 litter + its puppies"

    class Status(models.TextChoices):
        CREATED = "created", "Created"
        PENDING = "pending", "Awaiting payment"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"

    SINGLE_DOG_PRICE_KOBO = 50_000
    MULTI_DOG_PRICE_KOBO = 150_000
    LITTER_PRICE_KOBO = 100_000
    MULTI_DOG_MIN_COUNT = 2
    MULTI_DOG_MAX_COUNT = 6

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ancestry_submission_payments",
    )
    kennel = models.ForeignKey(
        "registry.Kennel",
        on_delete=models.PROTECT,
        related_name="submission_payments",
    )
    package = models.CharField(max_length=20, choices=Package.choices)
    dog_count = models.PositiveSmallIntegerField(default=1)
    amount_kobo = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="NGN")
    reference = models.CharField(max_length=80, unique=True)
    access_code = models.CharField(max_length=120, blank=True)
    authorization_url = models.URLField(max_length=500, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CREATED,
        db_index=True,
    )
    paystack_transaction_id = models.CharField(max_length=40, blank=True)
    raw_response = models.JSONField(default=dict, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    @classmethod
    def price_for(cls, package, dog_count=1):
        if package == cls.Package.SINGLE_DOG:
            return cls.SINGLE_DOG_PRICE_KOBO
        if package == cls.Package.MULTI_DOG:
            return cls.MULTI_DOG_PRICE_KOBO
        if package == cls.Package.LITTER:
            return cls.LITTER_PRICE_KOBO
        raise ValidationError("Unknown submission package.")

    @property
    def amount_naira(self):
        return self.amount_kobo // 100

    def clean(self):
        super().clean()
        if self.package == self.Package.SINGLE_DOG and self.dog_count != 1:
            raise ValidationError({"dog_count": "A single-dog package contains exactly one dog."})
        if (
            self.package == self.Package.MULTI_DOG
            and not self.MULTI_DOG_MIN_COUNT <= self.dog_count <= self.MULTI_DOG_MAX_COUNT
        ):
            raise ValidationError(
                {
                    "dog_count": (
                        f"A multi-dog package must contain "
                        f"{self.MULTI_DOG_MIN_COUNT}–{self.MULTI_DOG_MAX_COUNT} dogs."
                    )
                }
            )
        if self.package == self.Package.LITTER and self.dog_count != 0:
            raise ValidationError({"dog_count": "Litter packages use the litter and puppy workflow."})

    def __str__(self):
        return f"{self.get_package_display()} · {self.reference}"


class PaymentSubmissionLink(models.Model):
    class SlotKind(models.TextChoices):
        DOG = "dog", "Dog"
        LITTER = "litter", "Litter"
        PUPPY = "puppy", "Litter puppy"

    payment = models.ForeignKey(
        SubmissionPayment,
        on_delete=models.PROTECT,
        related_name="submission_links",
    )
    submission = models.OneToOneField(
        "registry.Submission",
        on_delete=models.PROTECT,
        related_name="payment_link",
    )
    slot_kind = models.CharField(max_length=12, choices=SlotKind.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)

    def __str__(self):
        return f"{self.payment.reference} · {self.get_slot_kind_display()}"
