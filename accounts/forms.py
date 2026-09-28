from django import forms
from django.core.validators import FileExtensionValidator
from django.db.models import Q

from registry.models import Dog, DogDocument, DogSource, Kennel, Litter, Submission, VerificationState


class DogSubmissionForm(forms.Form):
    name = forms.CharField(max_length=220)
    sex = forms.ChoiceField(choices=Dog.Sex.choices)
    date_of_birth = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    colour = forms.CharField(max_length=100, required=False)
    country = forms.CharField(max_length=80, required=False)
    bloodline = forms.CharField(max_length=220, required=False)
    kennel = forms.ModelChoiceField(queryset=Kennel.objects.none())
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
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp"])]
    )
    caption = forms.CharField(max_length=220, required=False)
    is_primary = forms.BooleanField(required=False)
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))


class DogDocumentSubmissionForm(forms.Form):
    title = forms.CharField(max_length=220)
    document_type = forms.ChoiceField(choices=DogDocument.DocumentType.choices)
    attachment = forms.FileField(
        validators=[FileExtensionValidator(["pdf", "jpg", "jpeg", "png", "webp"])]
    )
    is_public = forms.BooleanField(
        required=False,
        help_text="A moderator still controls approval and publication.",
    )
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))


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


class ReviewSubmissionForm(forms.Form):
    resolution_notes = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 3})
    )


class MergeDogsForm(forms.Form):
    canonical = forms.ModelChoiceField(queryset=Dog.objects.order_by("name"))
    duplicate = forms.ModelChoiceField(queryset=Dog.objects.order_by("name"))

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("canonical") == cleaned.get("duplicate"):
            raise forms.ValidationError("Choose two different dog records.")
        return cleaned



class VerificationEventForm(forms.Form):
    dog = forms.ModelChoiceField(queryset=Dog.objects.order_by("name"))
    field_name = forms.CharField(
        max_length=80,
        required=False,
        help_text="Leave blank to update the dog's overall verification state.",
    )
    state = forms.ChoiceField(choices=VerificationState.choices)
    source = forms.ModelChoiceField(
        queryset=DogSource.objects.select_related("dog").order_by("dog__name", "-created_at"),
        required=False,
    )
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def clean(self):
        cleaned = super().clean()
        dog = cleaned.get("dog")
        source = cleaned.get("source")
        if dog and source and source.dog_id != dog.pk:
            self.add_error("source", "The selected source belongs to a different dog.")
        return cleaned



class KennelClaimForm(forms.Form):
    relationship = forms.CharField(
        max_length=180,
        help_text="Describe your relationship to this kennel (owner, breeder, manager, etc.).",
    )
    evidence = forms.FileField(
        required=False,
        validators=[FileExtensionValidator(["pdf", "jpg", "jpeg", "png", "webp"])],
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
