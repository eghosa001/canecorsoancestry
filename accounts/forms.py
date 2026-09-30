from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db.models import Q
from django.utils.text import slugify

from registry.models import DisputeCase, Dog, DogDocument, DogRegistration, DogSource, Kennel, Litter, Submission, VerificationState


IMAGE_MAX_BYTES = 10 * 1024 * 1024
DOCUMENT_MAX_BYTES = 20 * 1024 * 1024


def validate_image_upload(upload):
    if upload.size > IMAGE_MAX_BYTES:
        raise ValidationError("Image files must be 10 MB or smaller.")
    header = upload.read(16)
    upload.seek(0)
    is_jpeg = header.startswith(b"\xff\xd8\xff")
    is_png = header.startswith(b"\x89PNG\r\n\x1a\n")
    is_webp = len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP"
    if not (is_jpeg or is_png or is_webp):
        raise ValidationError("The uploaded image content is not a valid JPEG, PNG or WebP file.")


def validate_document_upload(upload):
    if upload.size > DOCUMENT_MAX_BYTES:
        raise ValidationError("Evidence files must be 20 MB or smaller.")
    header = upload.read(16)
    upload.seek(0)
    is_pdf = header.startswith(b"%PDF-")
    is_jpeg = header.startswith(b"\xff\xd8\xff")
    is_png = header.startswith(b"\x89PNG\r\n\x1a\n")
    is_webp = len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP"
    if not (is_pdf or is_jpeg or is_png or is_webp):
        raise ValidationError("The uploaded evidence is not a valid PDF, JPEG, PNG or WebP file.")


class MemberSignUpForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username", "email")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account already uses this email address.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user


class DogSubmissionForm(forms.Form):
    name = forms.CharField(max_length=220)
    sex = forms.ChoiceField(choices=Dog.Sex.choices)
    date_of_birth = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    colour = forms.CharField(max_length=100, required=False)
    country = forms.CharField(max_length=80, required=False)
    bloodline = forms.CharField(max_length=220, required=False)
    kennel = forms.ModelChoiceField(queryset=Kennel.objects.none(), required=False)
    sire = forms.ModelChoiceField(queryset=Dog.objects.none(), required=False)
    dam = forms.ModelChoiceField(queryset=Dog.objects.none(), required=False)
    registration = forms.CharField(max_length=120, required=False)
    litter = forms.ModelChoiceField(queryset=Litter.objects.none(), required=False)
    bio = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 4}))
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        kennel_ids = []
        if user and user.is_authenticated:
            kennel_ids = user.kennel_memberships.values_list("kennel_id", flat=True)
        self.fields["kennel"].queryset = Kennel.objects.filter(pk__in=kennel_ids)
        related_dogs = Dog.objects.filter(
            Q(is_public=True) | Q(kennel_id__in=kennel_ids)
        ).distinct().order_by("name")
        self.fields["sire"].queryset = related_dogs
        self.fields["dam"].queryset = related_dogs
        self.fields["litter"].queryset = Litter.objects.filter(
            kennel_id__in=kennel_ids
        ).order_by("-date_of_birth", "code")

    def clean(self):
        cleaned = super().clean()
        sire = cleaned.get("sire")
        dam = cleaned.get("dam")
        if sire and sire.sex == Dog.Sex.FEMALE:
            self.add_error("sire", "The selected sire is recorded as female.")
        if dam and dam.sex == Dog.Sex.MALE:
            self.add_error("dam", "The selected dam is recorded as male.")

        registration = (cleaned.get("registration") or "").strip()
        if registration and DogRegistration.objects.filter(
            authority__isnull=True, number__iexact=registration
        ).exists():
            self.add_error(
                "registration",
                "This registration number is already attached to a dog. Open the existing record instead of creating a duplicate.",
            )

        name = (cleaned.get("name") or "").strip()
        date_of_birth = cleaned.get("date_of_birth")
        if name and date_of_birth:
            likely = Dog.objects.filter(
                name__iexact=name,
                date_of_birth=date_of_birth,
                sire=sire,
                dam=dam,
            ).first()
            if likely:
                self.add_error(
                    "name",
                    f"A likely matching dog already exists: {likely.name}. Use the existing record or submit a correction.",
                )
        return cleaned


class DogCorrectionForm(forms.ModelForm):
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Explain what changed and why.",
    )

    class Meta:
        model = Dog
        fields = (
            "name",
            "sex",
            "date_of_birth",
            "colour",
            "country",
            "bloodline",
            "sire",
            "dam",
            "litter",
            "bio",
        )
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
            "bio": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        kennel_ids = []
        if user and user.is_authenticated:
            kennel_ids = user.kennel_memberships.values_list("kennel_id", flat=True)
        related_dogs = Dog.objects.filter(
            Q(is_public=True) | Q(kennel_id__in=kennel_ids)
        ).distinct().order_by("name")
        self.fields["sire"].queryset = related_dogs
        self.fields["dam"].queryset = related_dogs
        self.fields["litter"].queryset = Litter.objects.filter(
            kennel_id__in=kennel_ids
        ).order_by("-date_of_birth", "code")

    def clean(self):
        cleaned = super().clean()
        dog = self.instance
        if cleaned.get("sire") == dog:
            self.add_error("sire", "A dog cannot be its own sire.")
        if cleaned.get("dam") == dog:
            self.add_error("dam", "A dog cannot be its own dam.")
        return cleaned


class DogImageSubmissionForm(forms.Form):
    attachment = forms.FileField(
        validators=[
            FileExtensionValidator(["jpg", "jpeg", "png", "webp"]),
            validate_image_upload,
        ]
    )
    caption = forms.CharField(max_length=220, required=False)
    is_primary = forms.BooleanField(required=False)
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))


class DogDocumentSubmissionForm(forms.Form):
    title = forms.CharField(max_length=220)
    document_type = forms.ChoiceField(choices=DogDocument.DocumentType.choices)
    attachment = forms.FileField(
        validators=[
            FileExtensionValidator(["pdf", "jpg", "jpeg", "png", "webp"]),
            validate_document_upload,
        ]
    )
    is_public = forms.BooleanField(
        required=False,
        help_text="A moderator still controls approval and publication.",
    )
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))


class KennelCreateForm(forms.Form):
    name = forms.CharField(max_length=180, label="Kennel / breeder brand name")
    country = forms.CharField(max_length=80, required=False)
    city = forms.CharField(max_length=120, required=False)
    website = forms.URLField(required=False)
    description = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 5}))
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Optional evidence or context for the moderator reviewing this kennel identity.",
    )

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split()).strip()
        candidate_slug = slugify(name)[:190]
        if not candidate_slug:
            raise forms.ValidationError("Enter a usable kennel or breeder brand name.")
        if Kennel.objects.filter(
            Q(name__iexact=name) | Q(slug__iexact=candidate_slug)
        ).exists():
            raise forms.ValidationError(
                "That kennel or breeder brand already exists. Claim the existing profile instead."
            )
        if Submission.objects.filter(
            kind=Submission.Kind.KENNEL_CREATE,
            status=Submission.Status.PENDING,
            payload__slug=candidate_slug,
        ).exists():
            raise forms.ValidationError(
                "That kennel or breeder brand name is already awaiting review."
            )
        return name


class KennelEditForm(forms.ModelForm):
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Optional note for the moderator reviewing this change.",
    )

    class Meta:
        model = Kennel
        fields = ("name", "country", "city", "description", "website")
        widgets = {"description": forms.Textarea(attrs={"rows": 5})}

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split()).strip()
        candidate_slug = slugify(name)[:190]
        conflict = Kennel.objects.exclude(pk=self.instance.pk).filter(
            Q(name__iexact=name) | Q(slug__iexact=candidate_slug)
        ).exists()
        if conflict:
            raise forms.ValidationError(
                "Another kennel or breeder brand already uses this name."
            )
        return name


class ReviewSubmissionForm(forms.Form):
    resolution_notes = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 3})
    )


class DogReferenceField(forms.CharField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault(
            "help_text",
            "Enter the exact dog name or UUID. Use UUID when names are duplicated.",
        )
        super().__init__(*args, **kwargs)

    def clean(self, value):
        value = super().clean(value).strip()
        by_id = None
        try:
            by_id = Dog.objects.filter(pk=value).first()
        except (TypeError, ValueError):
            by_id = None
        if by_id:
            return by_id

        matches = list(Dog.objects.filter(name__iexact=value).order_by("pk")[:2])
        if not matches:
            raise forms.ValidationError("No dog matches that exact name or UUID.")
        if len(matches) > 1:
            raise forms.ValidationError(
                "More than one dog has that name. Use the UUID shown by moderator search."
            )
        return matches[0]


class MergeDogsForm(forms.Form):
    canonical = DogReferenceField(label="Canonical dog")
    duplicate = DogReferenceField(label="Duplicate to retire")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("canonical") == cleaned.get("duplicate"):
            raise forms.ValidationError("Choose two different dog records.")
        return cleaned


class VerificationEventForm(forms.Form):
    dog = DogReferenceField()
    field_name = forms.CharField(
        max_length=80,
        required=False,
        help_text="Leave blank to update the dog's overall verification state.",
    )
    state = forms.ChoiceField(choices=VerificationState.choices)
    source_id = forms.IntegerField(
        required=False,
        min_value=1,
        label="Source ID",
        help_text="Optional evidence source ID already attached to this dog.",
    )
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def clean(self):
        cleaned = super().clean()
        dog = cleaned.get("dog")
        source_id = cleaned.get("source_id")
        source = None
        if source_id:
            source = DogSource.objects.filter(pk=source_id).first()
            if source is None:
                self.add_error("source_id", "No evidence source has that ID.")
            elif dog and source.dog_id != dog.pk:
                self.add_error(
                    "source_id",
                    "The selected source belongs to a different dog.",
                )
        cleaned["source"] = source
        return cleaned



class KennelClaimForm(forms.Form):
    relationship = forms.CharField(
        max_length=180,
        help_text="Describe your relationship to this kennel (owner, breeder, manager, etc.).",
    )
    evidence = forms.FileField(
        required=False,
        validators=[
            FileExtensionValidator(["pdf", "jpg", "jpeg", "png", "webp"]),
            validate_document_upload,
        ],
        help_text="Optional supporting document or image.",
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Add any information a moderator should use when checking the claim.",
    )


class LitterSubmissionForm(forms.Form):
    code = forms.CharField(max_length=80)
    kennel = forms.ModelChoiceField(queryset=Kennel.objects.none())
    sire = forms.ModelChoiceField(queryset=Dog.objects.none(), required=False)
    dam = forms.ModelChoiceField(queryset=Dog.objects.none(), required=False)
    date_of_birth = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 4}))
    review_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Optional note for the moderator reviewing this litter.",
    )

    def __init__(self, *args, user=None, kennel=None, litter=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user and user.is_authenticated:
            kennel_ids = user.kennel_memberships.filter(
                role__in=["owner", "editor"]
            ).values_list("kennel_id", flat=True)
        else:
            kennel_ids = []
        self.fields["kennel"].queryset = Kennel.objects.filter(pk__in=kennel_ids)

        related_dogs = Dog.objects.filter(
            Q(is_public=True) | Q(kennel_id__in=kennel_ids)
        ).distinct().order_by("name")
        self.fields["sire"].queryset = related_dogs
        self.fields["dam"].queryset = related_dogs

        if kennel:
            self.fields["kennel"].initial = kennel
        if litter:
            self.initial.update(
                {
                    "code": litter.code,
                    "kennel": litter.kennel,
                    "sire": litter.sire,
                    "dam": litter.dam,
                    "date_of_birth": litter.date_of_birth,
                    "notes": litter.notes,
                }
            )

    def clean_code(self):
        code = self.cleaned_data["code"].strip()
        return code

    def clean(self):
        cleaned = super().clean()
        sire = cleaned.get("sire")
        dam = cleaned.get("dam")
        if sire and dam and sire == dam:
            self.add_error("dam", "Sire and dam must be different dogs.")
        if sire and sire.sex == Dog.Sex.FEMALE:
            self.add_error("sire", "The selected sire is recorded as female.")
        if dam and dam.sex == Dog.Sex.MALE:
            self.add_error("dam", "The selected dam is recorded as male.")
        return cleaned


class DocumentVisibilityForm(forms.Form):
    is_public = forms.BooleanField(
        required=False,
        label="Publish this document on the public dog profile",
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Optional note explaining the visibility change.",
    )



class DisputeForm(forms.Form):
    reason = forms.ChoiceField(choices=DisputeCase.Reason.choices)
    details = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text="Describe the exact fact or relationship you believe should be reviewed.",
    )
    attachment = forms.FileField(
        required=False,
        validators=[
            FileExtensionValidator(["pdf", "jpg", "jpeg", "png", "webp"]),
            validate_document_upload,
        ],
        help_text="Optional pedigree, certificate, screenshot or other supporting evidence.",
    )


class BulkModerationForm(forms.Form):
    ACTIONS = (
        ("assign_me", "Assign selected to me"),
        ("unassign", "Remove assignee"),
        ("priority_low", "Set priority: Low"),
        ("priority_normal", "Set priority: Normal"),
        ("priority_high", "Set priority: High"),
        ("priority_urgent", "Set priority: Urgent"),
        ("reject", "Reject selected"),
    )

    action = forms.ChoiceField(choices=ACTIONS)
    resolution_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Required when rejecting multiple submissions.",
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("action") == "reject" and not cleaned.get("resolution_notes", "").strip():
            self.add_error(
                "resolution_notes",
                "A rejection reason is required for a bulk rejection.",
            )
        return cleaned


class DuplicateMatchForm(forms.Form):
    duplicate_q = forms.CharField(
        max_length=220,
        label="Find a dog",
        help_text="Search by dog name, alias or external registration number.",
    )
