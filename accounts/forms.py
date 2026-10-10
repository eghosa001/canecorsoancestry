from io import BytesIO
from pathlib import Path

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import Q
from django.utils.text import slugify
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

from registry.models import DisputeCase, Dog, DogDocument, DogImage, DogIdentityNumber, DogRegistration, DogSource, Kennel, KennelMembership, Litter, ModerationRoleAssignment, Submission, SubmissionEvidence, VerificationState

from .models import Profile, SubmissionPayment


IMAGE_MAX_BYTES = 20 * 1024 * 1024
DOCUMENT_MAX_BYTES = 20 * 1024 * 1024
IMAGE_ACCEPT = "image/*"
DOCUMENT_ACCEPT = "application/pdf,image/*"
PHOTO_MAX_DIMENSION = 3200

# Register HEIC/HEIF support, then let Pillow validate image content rather than
# trusting a filename extension or browser-reported MIME type. This keeps the
# submission portal compatible with normal phone, camera and downloaded images.
register_heif_opener(thumbnails=False)


def _is_pdf(upload):
    header = upload.read(5)
    upload.seek(0)
    return header.startswith(b"%PDF-")


def _verify_uploaded_image(upload):
    try:
        with Image.open(upload) as image:
            if image.width > 12000 or image.height > 12000:
                raise ValidationError("Image dimensions must not exceed 12,000 × 12,000 pixels.")
            if image.width * image.height > 60_000_000:
                raise ValidationError("Image contains too many pixels.")
            image.verify()
    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise ValidationError(
            "The uploaded file is not a readable photo. Choose a normal image from your gallery, camera or files."
        ) from exc
    finally:
        upload.seek(0)


def validate_image_upload(upload):
    if upload.size > IMAGE_MAX_BYTES:
        raise ValidationError("Image files must be 20 MB or smaller.")
    _verify_uploaded_image(upload)


def validate_document_upload(upload):
    if upload.size > DOCUMENT_MAX_BYTES:
        raise ValidationError("Evidence files must be 20 MB or smaller.")
    if _is_pdf(upload):
        return
    _verify_uploaded_image(upload)


def normalize_image_upload(upload):
    """Normalize any accepted raster image to a compact, browser-safe JPEG."""
    if not upload or _is_pdf(upload):
        return upload

    try:
        with Image.open(upload) as source:
            source.load()
            image = ImageOps.exif_transpose(source)

            if image.width > PHOTO_MAX_DIMENSION or image.height > PHOTO_MAX_DIMENSION:
                image.thumbnail(
                    (PHOTO_MAX_DIMENSION, PHOTO_MAX_DIMENSION),
                    Image.Resampling.LANCZOS,
                )

            if image.mode in {"RGBA", "LA"} or (
                image.mode == "P" and "transparency" in image.info
            ):
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            elif image.mode != "RGB":
                image = image.convert("RGB")

            output = BytesIO()
            image.save(
                output,
                format="JPEG",
                quality=92,
                optimize=True,
                progressive=True,
            )
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise ValidationError(
            "This photo could not be prepared for upload. Choose another image and try again."
        ) from exc
    finally:
        upload.seek(0)

    stem = Path(upload.name or "photo").stem or "photo"
    return SimpleUploadedFile(
        f"{stem}.jpg",
        output.getvalue(),
        content_type="image/jpeg",
    )


class MemberProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ("country", "bio")
        widgets = {
            "bio": forms.Textarea(attrs={"rows": 5}),
        }
        labels = {
            "country": "Country",
            "bio": "About your kennel / profile",
        }


class HealthRecordSubmissionForm(forms.Form):
    EVIDENCE_TYPES = (
        ("health", "Health test"),
        ("dna", "DNA / parentage test"),
    )

    evidence_type = forms.ChoiceField(
        choices=EVIDENCE_TYPES,
        label="Record type",
    )
    test_type = forms.CharField(
        max_length=100,
        label="Test / marker",
        help_text="For example: hip score, elbow score, cardiac exam, DM, DSRA or DNA parentage.",
    )
    result = forms.CharField(
        max_length=160,
        help_text="Enter the result exactly as shown on the supporting evidence.",
    )
    tested_on = forms.DateField(
        required=False,
        label="Test date",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    attachment = forms.FileField(
        label="Supporting result / certificate",
        widget=forms.ClearableFileInput(
            attrs={"accept": DOCUMENT_ACCEPT}
        ),
        validators=[
            validate_document_upload,
        ],
        help_text="Required evidence. PDF or a readable image from your phone, camera or files, up to 20 MB. Kept private unless separately approved for publication.",
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Optional context for the administrator reviewing this result.",
    )

    def clean_attachment(self):
        return normalize_image_upload(self.cleaned_data.get("attachment"))


class VerificationResendForm(forms.Form):
    email = forms.EmailField()


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )

    def clean(self):
        email = (self.cleaned_data.get("username") or "").strip().lower()
        if email:
            user = get_user_model().objects.filter(email__iexact=email).only("username").first()
            if user:
                self.cleaned_data["username"] = user.get_username()
        return super().clean()


class MemberSignUpForm(UserCreationForm):
    username = forms.CharField(required=False, widget=forms.HiddenInput())
    kennel_name = forms.CharField(
        max_length=180,
        label="Kennel name",
        help_text="This is the public account name shown across the site.",
    )
    email = forms.EmailField(
        required=True,
        label="Email",
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username", "kennel_name", "email")

    def clean_kennel_name(self):
        name = " ".join(self.cleaned_data["kennel_name"].split()).strip()
        account_username = slugify(name)[:150]
        if not account_username:
            raise forms.ValidationError("Enter a usable kennel name.")
        if get_user_model().objects.filter(username__iexact=account_username).exists():
            raise forms.ValidationError("An account already uses this kennel name.")
        return name

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account already uses this email address.")
        return email

    def clean(self):
        cleaned = super().clean()
        kennel_name = cleaned.get("kennel_name")
        if kennel_name:
            cleaned["username"] = slugify(kennel_name)[:150]
            self.instance.username = cleaned["username"]
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = slugify(self.cleaned_data["kennel_name"])[:150]
        user.email = self.cleaned_data["email"]
        user.is_staff = False
        user.is_superuser = False
        if commit:
            user.save()
        return user


class ModeratorAccountCreateForm(UserCreationForm):
    email = forms.EmailField(
        required=True,
        label="Staff email",
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )
    role = forms.ChoiceField(
        choices=(
            (ModerationRoleAssignment.Role.REVIEWER, "Moderator"),
            (ModerationRoleAssignment.Role.SENIOR, "Senior Moderator"),
        ),
        help_text="Super Admin accounts are created separately as Django superusers.",
    )

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
        user.email = self.cleaned_data["email"].strip().lower()
        user.is_staff = False
        user.is_superuser = False
        if commit:
            user.save()
        return user


def _configure_parent_autocomplete(form, related_dogs, *, initial_sire=None, initial_dam=None):
    """Keep parent IDs server-validated without rendering tens of thousands of <option>s."""
    base_order = list(form.fields)
    initial_by_role = {"sire": initial_sire, "dam": initial_dam}
    sex_by_role = {"sire": Dog.Sex.MALE, "dam": Dog.Sex.FEMALE}

    for role in ("sire", "dam"):
        form.fields[role].queryset = related_dogs
        form.fields[role].widget = forms.HiddenInput()
        query_name = f"{role}_q"
        form.fields[query_name] = forms.CharField(
            required=False,
            label=role.title(),
            help_text="Type at least 2 characters and choose a matching dog. Exact unique names or registrations also work.",
            widget=forms.TextInput(
                attrs={
                    "data-dog-autocomplete": "",
                    "data-dog-autocomplete-mode": "fill",
                    "data-dog-autocomplete-target": f"id_{role}",
                    "data-dog-sex": sex_by_role[role],
                    "autocomplete": "off",
                    "placeholder": f"Search {role} by name or registration",
                }
            ),
        )
        if not form.is_bound and initial_by_role[role]:
            form.initial[query_name] = initial_by_role[role].name

    ordered = []
    for name in base_order:
        ordered.append(name)
        if name in {"sire", "dam"}:
            ordered.append(f"{name}_q")
    form.order_fields(ordered)


def _resolve_parent_autocomplete(form, cleaned, role, expected_sex):
    selected = cleaned.get(role)
    query = (cleaned.get(f"{role}_q") or "").strip()

    if selected is None and query:
        matches = list(
            form.fields[role]
            .queryset.filter(
                Q(name__iexact=query)
                | Q(registrations__number__iexact=query)
            )
            .distinct()
            .order_by("name")[:2]
        )
        if len(matches) == 1:
            selected = matches[0]
        elif len(matches) > 1:
            form.add_error(
                f"{role}_q",
                "More than one dog matches that value. Choose a suggestion so the exact dog ID is used.",
            )
        else:
            form.add_error(
                f"{role}_q",
                "No matching dog was found. Type at least 2 characters and choose a suggestion.",
            )

    if selected and selected.sex not in {expected_sex, Dog.Sex.UNKNOWN}:
        form.add_error(
            f"{role}_q",
            f"The selected {role} is recorded as {selected.get_sex_display().lower()}.",
        )

    cleaned[role] = selected
    return selected


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
    microchip_number = forms.CharField(
        max_length=160,
        required=False,
        help_text="Optional. Used privately for identity verification and duplicate checking.",
    )
    litter = forms.ModelChoiceField(queryset=Litter.objects.none(), required=False)
    bio = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 4}))
    primary_photo = forms.FileField(
        required=False,
        label="Primary photo",
        widget=forms.ClearableFileInput(
            attrs={"accept": IMAGE_ACCEPT}
        ),
        validators=[
            validate_image_upload,
        ],
        help_text="Optional. Choose a photo from your phone, camera or files, up to 20 MB. This becomes the dog's first profile photo after approval.",
    )
    photo_caption = forms.CharField(
        max_length=220,
        required=False,
        label="Photo caption",
        help_text="Optional caption for the submitted primary photo.",
    )
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def clean_primary_photo(self):
        return normalize_image_upload(self.cleaned_data.get("primary_photo"))

    def __init__(self, *args, user=None, kennel=None, **kwargs):
        super().__init__(*args, **kwargs)
        kennel_ids = []
        if user and user.is_authenticated:
            kennel_ids = user.kennel_memberships.values_list("kennel_id", flat=True)
        self.fields["kennel"].queryset = Kennel.objects.filter(pk__in=kennel_ids)
        if kennel is not None:
            self.fields["kennel"].queryset = Kennel.objects.filter(pk=kennel.pk)
            self.fields["kennel"].initial = kennel
            self.fields["kennel"].required = True
            self.fields["kennel"].disabled = True
        related_dogs = Dog.objects.filter(
            Q(is_public=True) | Q(kennel_id__in=kennel_ids)
        )
        _configure_parent_autocomplete(self, related_dogs)
        self.fields["litter"].queryset = Litter.objects.filter(
            kennel_id__in=kennel_ids
        ).order_by("-date_of_birth", "code")

    def clean(self):
        cleaned = super().clean()
        sire = _resolve_parent_autocomplete(self, cleaned, "sire", Dog.Sex.MALE)
        dam = _resolve_parent_autocomplete(self, cleaned, "dam", Dog.Sex.FEMALE)

        # Duplicate identity signals are deliberately not rejected here. They are
        # evaluated server-side by the verification engine so legitimate corrections
        # can reach the admin review queue with an explainable warning.
        return cleaned


class PaymentPackageForm(forms.Form):
    kennel = forms.ModelChoiceField(
        queryset=Kennel.objects.none(),
        help_text="Only administrator-verified kennels that you own or edit can be used.",
    )
    package = forms.ChoiceField(choices=SubmissionPayment.Package.choices)
    dog_count = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=SubmissionPayment.MULTI_DOG_MAX_COUNT,
        label="Number of dogs",
        help_text="Use 1 for a single dog, or choose 2–6 for the ₦1,500 multi-dog package.",
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user and user.is_authenticated:
            kennel_ids = user.kennel_memberships.filter(
                role__in=[KennelMembership.Role.OWNER, KennelMembership.Role.EDITOR],
                kennel__verified_at__isnull=False,
            ).values_list("kennel_id", flat=True)
        else:
            kennel_ids = []
        self.fields["kennel"].queryset = Kennel.objects.filter(pk__in=kennel_ids).order_by("name")

    def clean(self):
        cleaned = super().clean()
        package = cleaned.get("package")
        dog_count = cleaned.get("dog_count")
        if package == SubmissionPayment.Package.SINGLE_DOG:
            dog_count = 1
        elif package == SubmissionPayment.Package.MULTI_DOG:
            if (
                dog_count is None
                or not SubmissionPayment.MULTI_DOG_MIN_COUNT
                <= dog_count
                <= SubmissionPayment.MULTI_DOG_MAX_COUNT
            ):
                self.add_error(
                    "dog_count",
                    (
                        f"Choose between {SubmissionPayment.MULTI_DOG_MIN_COUNT} "
                        f"and {SubmissionPayment.MULTI_DOG_MAX_COUNT} dogs."
                    ),
                )
        elif package == SubmissionPayment.Package.LITTER:
            dog_count = 0
        if package and not self.errors:
            cleaned["dog_count"] = dog_count
            cleaned["amount_kobo"] = SubmissionPayment.price_for(package, dog_count)
        return cleaned


class LitterPuppySubmissionForm(forms.Form):
    name = forms.CharField(max_length=220)
    sex = forms.ChoiceField(choices=Dog.Sex.choices)
    date_of_birth = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        help_text="Enter the puppy's actual DOB. It will be checked against the paid litter.",
    )
    colour = forms.CharField(max_length=100, required=False)
    country = forms.CharField(max_length=80, required=False)
    bloodline = forms.CharField(max_length=220, required=False)
    registration = forms.CharField(max_length=120, required=False)
    microchip_number = forms.CharField(
        max_length=160,
        required=False,
        help_text="Optional. Kept for private identity verification.",
    )
    bio = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 4}))
    primary_photo = forms.FileField(
        required=False,
        label="Primary photo",
        widget=forms.ClearableFileInput(
            attrs={"accept": IMAGE_ACCEPT}
        ),
        validators=[
            validate_image_upload,
        ],
        help_text="Optional. Choose a photo from your phone, camera or files, up to 20 MB. It becomes the puppy's first profile photo after approval.",
    )
    photo_caption = forms.CharField(
        max_length=220,
        required=False,
        label="Photo caption",
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Optional note for the administrator verifying this puppy.",
    )

    def clean_primary_photo(self):
        return normalize_image_upload(self.cleaned_data.get("primary_photo"))

    def clean_registration(self):
        # Existing numbers are allowed into moderation so the verifier can explain
        # the conflict rather than treating every discrepancy as fraud.
        return (self.cleaned_data.get("registration") or "").strip()


class DogCorrectionForm(forms.ModelForm):
    registration = forms.CharField(
        max_length=120,
        required=False,
        help_text="Changing a published registration number is treated as a protected identity change.",
    )
    microchip_number = forms.CharField(
        max_length=160,
        required=False,
        help_text="Optional private identity number. Changes are reviewed and audited.",
    )
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
        )
        parent_ids = [pk for pk in (self.instance.sire_id, self.instance.dam_id) if pk]
        parents = Dog.objects.only("id", "name").in_bulk(parent_ids)
        _configure_parent_autocomplete(
            self,
            related_dogs,
            initial_sire=parents.get(self.instance.sire_id),
            initial_dam=parents.get(self.instance.dam_id),
        )
        self.fields["litter"].queryset = Litter.objects.filter(
            kennel_id__in=kennel_ids
        ).order_by("-date_of_birth", "code")
        registration = self.instance.registrations.filter(authority__isnull=True).first()
        microchip = self.instance.identity_numbers.filter(
            kind=DogIdentityNumber.Kind.MICROCHIP
        ).first()
        self.fields["registration"].initial = registration.number if registration else ""
        self.fields["microchip_number"].initial = microchip.value if microchip else ""

    def clean(self):
        cleaned = super().clean()
        dog = self.instance
        sire = _resolve_parent_autocomplete(self, cleaned, "sire", Dog.Sex.MALE)
        dam = _resolve_parent_autocomplete(self, cleaned, "dam", Dog.Sex.FEMALE)
        if sire == dog:
            self.add_error("sire_q", "A dog cannot be its own sire.")
        if dam == dog:
            self.add_error("dam_q", "A dog cannot be its own dam.")
        return cleaned


class DogImageSubmissionForm(forms.Form):
    attachment = forms.FileField(
        label="Photo",
        widget=forms.ClearableFileInput(
            attrs={"accept": IMAGE_ACCEPT}
        ),
        validators=[
            validate_image_upload,
        ],
        help_text="Choose a photo from your phone, camera or files, up to 20 MB.",
    )
    caption = forms.CharField(max_length=220, required=False)
    is_primary = forms.BooleanField(
        required=False,
        initial=True,
        label="Use as the main profile photo",
        help_text="Checked by default. Uncheck to add the approved photo to the gallery only.",
    )
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def clean_attachment(self):
        return normalize_image_upload(self.cleaned_data.get("attachment"))


class DogDocumentSubmissionForm(forms.Form):
    title = forms.CharField(max_length=220)
    achievement_title = forms.CharField(max_length=160, required=False)
    certificate_issuer = forms.CharField(max_length=160, required=False)
    certificate_awarded_on = forms.DateField(required=False)
    document_type = forms.ChoiceField(choices=[*DogDocument.DocumentType.choices, ("title_certificate", "Club title certificate")])
    attachment = forms.FileField(
        widget=forms.ClearableFileInput(
            attrs={"accept": DOCUMENT_ACCEPT}
        ),
        validators=[
            validate_document_upload,
        ]
    )
    is_public = forms.BooleanField(
        required=False,
        help_text="A moderator still controls approval and publication.",
    )
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def clean_attachment(self):
        return normalize_image_upload(self.cleaned_data.get("attachment"))

    def clean(self):
        values = super().clean()
        if (values.get("document_type") == DogDocument.DocumentType.TITLE_CERTIFICATE
                and not (values.get("achievement_title") or "").strip()):
            self.add_error("achievement_title", "Please enter the title shown on the document.")
        return values


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


class SubmissionEvidenceForm(forms.Form):
    evidence_type = forms.ChoiceField(choices=SubmissionEvidence.EvidenceType.choices)
    file = forms.FileField(
        widget=forms.ClearableFileInput(
            attrs={"accept": DOCUMENT_ACCEPT}
        ),
        validators=[
            validate_document_upload,
        ]
    )
    note = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Optional context for the reviewing administrator.",
    )

    def clean_file(self):
        return normalize_image_upload(self.cleaned_data.get("file"))


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
        except (TypeError, ValueError, ValidationError):
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
    confirm_merge = forms.BooleanField(
        label="I checked both records and confirm these are the same real dog.",
        help_text="The duplicate profile will retire and its parentage, descendants, registrations and records will be transferred.",
    )

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
        widget=forms.ClearableFileInput(attrs={"accept": DOCUMENT_ACCEPT}),
        validators=[
            validate_document_upload,
        ],
        help_text="Optional supporting document or image, including photos from phones and cameras.",
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Add any information a moderator should use when checking the claim.",
    )

    def clean_evidence(self):
        return normalize_image_upload(self.cleaned_data.get("evidence"))


class LitterSubmissionForm(forms.Form):
    code = forms.CharField(max_length=80, label="Litter ID")
    kennel = forms.ModelChoiceField(queryset=Kennel.objects.none())
    country = forms.CharField(
        max_length=80,
        required=False,
        help_text="Country where the litter was whelped, where known.",
    )
    declared_puppy_count = forms.IntegerField(
        required=False,
        min_value=1,
        label="Number of puppies",
        help_text="Declared litter size. Adult littermates can still be submitted later under this same litter.",
    )
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
        )
        initial_sire = litter.sire if litter and litter.sire_id else None
        initial_dam = litter.dam if litter and litter.dam_id else None
        _configure_parent_autocomplete(
            self,
            related_dogs,
            initial_sire=initial_sire,
            initial_dam=initial_dam,
        )

        if kennel:
            self.fields["kennel"].initial = kennel
        if litter:
            self.initial.update(
                {
                    "code": litter.code,
                    "kennel": litter.kennel,
                    "country": litter.country,
                    "declared_puppy_count": litter.declared_puppy_count,
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
        sire = _resolve_parent_autocomplete(self, cleaned, "sire", Dog.Sex.MALE)
        dam = _resolve_parent_autocomplete(self, cleaned, "dam", Dog.Sex.FEMALE)
        if sire and dam and sire == dam:
            self.add_error("dam_q", "Sire and dam must be different dogs.")
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
    target_image = forms.ModelChoiceField(
        queryset=DogImage.objects.none(), required=False,
        label="Incorrect photo (choose from uploaded photos)",
        help_text="Select the incorrect image, if listed. Imported source images can still be reported without selecting one.",
    )

    def __init__(self, *args, dog=None, **kwargs):
        super().__init__(*args, **kwargs)
        if dog is not None:
            self.fields["target_image"].queryset = DogImage.objects.filter(
                dog=dog,
            ).order_by("-is_primary", "sort_order", "created_at")
    details = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text="Describe the exact fact or relationship you believe should be reviewed.",
    )
    attachment = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={"accept": DOCUMENT_ACCEPT}),
        validators=[
            validate_document_upload,
        ],
        help_text="Optional pedigree, certificate, screenshot or other supporting evidence, including photos from phones and cameras.",
    )

    def clean_attachment(self):
        return normalize_image_upload(self.cleaned_data.get("attachment"))

    def clean(self):
        values = super().clean()
        if values.get("reason") == DisputeCase.Reason.PHOTO:
            uploaded = values.get("attachment")
            if uploaded and not uploaded.name.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                self.add_error("attachment", "A suggested replacement must be an image, not a PDF.")
        return values


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
