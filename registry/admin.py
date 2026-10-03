from django.contrib import admin

from .models import (
    DisputeCase,
    Dog,
    DogAlias,
    DogDocument,
    DogExternalKey,
    DogImage,
    DogRedirect,
    DogRegistration,
    DogSource,
    DogTitle,
    HealthRecord,
    Kennel,
    KennelMembership,
    Litter,
    MergeHistory,
    ModerationAudit,
    Notification,
    RegistrationAuthority,
    Submission,
    VerificationEvent,
)


class DogRegistrationInline(admin.TabularInline):
    model = DogRegistration
    extra = 0


class DogAliasInline(admin.TabularInline):
    model = DogAlias
    extra = 0


class DogExternalKeyInline(admin.TabularInline):
    model = DogExternalKey
    extra = 0


class DogTitleInline(admin.TabularInline):
    model = DogTitle
    extra = 0


@admin.register(Dog)
class DogAdmin(admin.ModelAdmin):
    list_display = ("name", "sex", "kennel", "verification_state", "is_public")
    list_filter = ("sex", "verification_state", "is_public", "country")
    search_fields = (
        "name",
        "bloodline",
        "aliases__name",
        "registrations__number",
        "external_keys__key",
    )
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("sire", "dam", "kennel", "litter")
    inlines = (
        DogAliasInline,
        DogExternalKeyInline,
        DogRegistrationInline,
        DogTitleInline,
    )


@admin.register(Kennel)
class KennelAdmin(admin.ModelAdmin):
    list_display = ("name", "country", "city", "verified_at")
    search_fields = ("name", "country", "city")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Litter)
class LitterAdmin(admin.ModelAdmin):
    list_display = ("code", "kennel", "date_of_birth", "is_public")
    search_fields = ("code",)


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = (
        "kind",
        "submitted_by",
        "dog",
        "litter",
        "document",
        "kennel",
        "status",
        "priority",
        "assigned_to",
        "created_at",
    )
    list_filter = ("kind", "status", "priority", "created_at")
    search_fields = (
        "dog__name",
        "litter__code",
        "document__title",
        "kennel__name",
        "submitted_by__username",
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(VerificationEvent)
class VerificationEventAdmin(admin.ModelAdmin):
    list_display = ("dog", "kennel", "field_name", "state", "reviewer", "created_at")
    list_filter = ("state", "created_at")
    search_fields = ("dog__name", "kennel__name", "field_name", "note")


@admin.register(MergeHistory)
class MergeHistoryAdmin(admin.ModelAdmin):
    list_display = ("retired_name", "canonical_dog", "performed_by", "created_at")
    search_fields = ("retired_name", "retired_slug", "canonical_dog__name")
    readonly_fields = (
        "canonical_dog",
        "retired_dog_id",
        "retired_slug",
        "retired_name",
        "performed_by",
        "summary",
        "created_at",
    )


@admin.register(KennelMembership)
class KennelMembershipAdmin(admin.ModelAdmin):
    list_display = ("kennel", "user", "role", "created_at")
    list_filter = ("role", "created_at")
    search_fields = ("kennel__name", "user__username", "user__email")
    autocomplete_fields = ("kennel", "user")

admin.site.register(RegistrationAuthority)
admin.site.register(DogImage)
admin.site.register(DogDocument)
admin.site.register(HealthRecord)
admin.site.register(DogSource)
admin.site.register(DogRedirect)
admin.site.register(Notification)



@admin.register(DisputeCase)
class DisputeCaseAdmin(admin.ModelAdmin):
    list_display = ("dog", "reason", "status", "opened_by", "assigned_to", "created_at")
    list_filter = ("reason", "status", "created_at")
    search_fields = ("dog__name", "opened_by__username", "details", "resolution_notes")


@admin.register(ModerationAudit)
class ModerationAuditAdmin(admin.ModelAdmin):
    list_display = ("action", "actor", "dog", "kennel", "litter", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("dog__name", "kennel__name", "litter__code", "actor__username", "note")
    readonly_fields = (
        "actor",
        "action",
        "dog",
        "kennel",
        "litter",
        "submission",
        "dispute",
        "summary",
        "note",
        "created_at",
    )
