from django.contrib import admin

from .models import (
    DisputeCase,
    EvidenceRequest,
    Dog,
    DogAlias,
    DogDocument,
    DogExternalKey,
    DogIdentityNumber,
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
    ModerationRoleAssignment,
    Notification,
    RegistrationAuthority,
    Submission,
    SubmissionEvidence,
    SubmissionReview,
    VerificationEvent,
    VerificationFinding,
    VerificationRule,
)


class DogRegistrationInline(admin.TabularInline):
    model = DogRegistration
    extra = 0

    def has_add_permission(self, request, obj=None):
        if obj and obj.is_public:
            return False
        return super().has_add_permission(request, obj)

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.is_public:
            return ("authority", "number", "issued_on")
        return ()

    def has_delete_permission(self, request, obj=None):
        if obj and obj.is_public:
            return False
        return super().has_delete_permission(request, obj)


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
    list_display = ("name", "sex", "kennel", "verification_state", "is_public", "is_record_locked")
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

    def get_readonly_fields(self, request, obj=None):
        protected = (
            "is_public",
            "is_record_locked",
            "record_locked_at",
            "record_locked_by",
        )
        if obj and obj.is_public:
            return protected + (
                "name",
                "sex",
                "date_of_birth",
                "colour",
                "country",
                "bloodline",
                "kennel",
                "sire",
                "dam",
                "litter",
                "bio",
                "verification_state",
            )
        return protected


@admin.register(Kennel)
class KennelAdmin(admin.ModelAdmin):
    list_display = ("name", "country", "city", "verified_at")
    search_fields = ("name", "country", "city")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("verified_at",)


@admin.register(Litter)
class LitterAdmin(admin.ModelAdmin):
    list_display = ("code", "kennel", "date_of_birth", "declared_puppy_count", "is_public", "is_record_locked")
    search_fields = ("code",)

    def get_readonly_fields(self, request, obj=None):
        protected = (
            "is_public",
            "is_record_locked",
            "record_locked_at",
            "record_locked_by",
        )
        if obj and obj.is_public:
            return protected + (
                "code",
                "kennel",
                "sire",
                "dam",
                "date_of_birth",
                "country",
                "declared_puppy_count",
                "notes",
            )
        return protected


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = (
        "kind",
        "submitted_by",
        "dog",
        "litter",
        "document",
        "kennel",
        "payment_state",
        "status",
        "risk_level",
        "verification_status",
        "requires_second_review",
        "priority",
        "assigned_admin",
        "created_at",
    )
    list_filter = ("kind", "status", "risk_level", "verification_status", "priority", "created_at")
    search_fields = (
        "dog__name",
        "litter__code",
        "document__title",
        "kennel__name",
        "submitted_by__username",
    )
    exclude = ("reviewed_by", "assigned_to")
    readonly_fields = (
        "status",
        "reviewed_by_admin",
        "assigned_admin",
        "reviewed_at",
        "resolution_notes",
        "risk_level",
        "verification_status",
        "verification_checked_at",
        "requires_second_review",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return bool(request.user and request.user.is_staff)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("payment_link__payment")

    @admin.display(description="Reviewed by")
    def reviewed_by_admin(self, obj):
        if not obj.reviewed_by_id:
            return "Not reviewed"
        assignment = ModerationRoleAssignment.objects.filter(
            user_id=obj.reviewed_by_id
        ).only("admin_number").first()
        return assignment.public_label if assignment else "Admin"

    @admin.display(description="Assigned admin")
    def assigned_admin(self, obj):
        if not obj.assigned_to_id:
            return "Unassigned"
        assignment = ModerationRoleAssignment.objects.filter(
            user_id=obj.assigned_to_id
        ).only("admin_number").first()
        return assignment.public_label if assignment else "Admin"

    @admin.display(description="Payment")
    def payment_state(self, obj):
        try:
            payment = obj.payment_link.payment
        except Exception:
            return "Not required"
        return f"{payment.get_status_display()} · ₦{payment.amount_naira}"


@admin.register(VerificationEvent)
class VerificationEventAdmin(admin.ModelAdmin):
    list_display = ("dog", "kennel", "field_name", "state", "reviewer_admin", "created_at")
    list_filter = ("state", "created_at")
    search_fields = ("dog__name", "kennel__name", "field_name", "note")
    exclude = ("reviewer",)
    readonly_fields = ("reviewer_admin",)

    @admin.display(description="Reviewer")
    def reviewer_admin(self, obj):
        if not obj.reviewer_id:
            return "System"
        assignment = ModerationRoleAssignment.objects.filter(
            user_id=obj.reviewer_id
        ).only("admin_number").first()
        return assignment.public_label if assignment else "Admin"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return bool(request.user and request.user.is_staff)


@admin.register(MergeHistory)
class MergeHistoryAdmin(admin.ModelAdmin):
    list_display = ("retired_name", "canonical_dog", "performed_by_admin", "created_at")
    search_fields = ("retired_name", "retired_slug", "canonical_dog__name")
    @admin.display(description="Performed by")
    def performed_by_admin(self, obj):
        if not obj.performed_by_id:
            return "System"
        assignment = ModerationRoleAssignment.objects.filter(
            user_id=obj.performed_by_id
        ).only("admin_number").first()
        return assignment.public_label if assignment else "Admin"

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

@admin.register(DogDocument)
class DogDocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "dog", "document_type", "is_public", "created_at")
    list_filter = ("document_type", "is_public", "created_at")
    search_fields = ("title", "dog__name", "submitted_by__username")
    readonly_fields = (
        "dog",
        "title",
        "document_type",
        "file",
        "is_public",
        "submitted_by",
        "source_submission",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

admin.site.register(HealthRecord)
admin.site.register(DogSource)
admin.site.register(DogRedirect)
admin.site.register(Notification)



@admin.register(DisputeCase)
class DisputeCaseAdmin(admin.ModelAdmin):
    list_display = ("dog", "reason", "status", "opened_by", "assigned_admin", "created_at")
    list_filter = ("reason", "status", "created_at")
    search_fields = ("dog__name", "opened_by__username", "details", "resolution_notes")

    @admin.display(description="Assigned admin")
    def assigned_admin(self, obj):
        if not obj.assigned_to_id:
            return "Unassigned"
        assignment = ModerationRoleAssignment.objects.filter(
            user_id=obj.assigned_to_id
        ).only("admin_number").first()
        return assignment.public_label if assignment else "Admin"


class AppendOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return bool(request.user and request.user.is_staff)


@admin.register(ModerationAudit)
class ModerationAuditAdmin(AppendOnlyAdmin):
    list_display = ("action", "public_actor", "dog", "kennel", "litter", "created_at")
    list_filter = ("action", "created_at")
    exclude = ("actor",)
    readonly_fields = ("public_actor",)
    search_fields = ("dog__name", "kennel__name", "litter__code", "actor_admin_number_snapshot", "note")

    @admin.display(description="Admin")
    def public_actor(self, obj):
        return obj.actor_admin_label


@admin.register(SubmissionReview)
class SubmissionReviewAdmin(AppendOnlyAdmin):
    list_display = ("submission", "action", "public_reviewer", "created_at")
    list_filter = ("action", "created_at")
    exclude = ("reviewer",)
    readonly_fields = ("public_reviewer",)
    search_fields = ("submission__id", "reviewer_admin_number_snapshot", "reason")

    @admin.display(description="Admin")
    def public_reviewer(self, obj):
        return obj.reviewer_admin_label


@admin.register(VerificationFinding)
class VerificationFindingAdmin(AppendOnlyAdmin):
    list_display = ("submission", "code", "risk_level", "is_current", "created_at")
    list_filter = ("risk_level", "is_current", "created_at")
    search_fields = ("submission__id", "code", "message")


@admin.register(SubmissionEvidence)
class SubmissionEvidenceAdmin(AppendOnlyAdmin):
    list_display = ("submission", "evidence_type", "uploaded_by_display", "created_at")
    list_filter = ("evidence_type", "created_at")
    exclude = ("uploaded_by",)
    readonly_fields = ("uploaded_by_display",)
    search_fields = ("submission__id", "sha256", "note")

    @admin.display(description="Uploaded by")
    def uploaded_by_display(self, obj):
        return obj.uploaded_by_display_label


@admin.register(EvidenceRequest)
class EvidenceRequestAdmin(AppendOnlyAdmin):
    list_display = ("submission", "status", "requested_by_admin", "created_at")
    list_filter = ("status", "created_at")
    exclude = ("requested_by",)
    readonly_fields = ("requested_by_admin",)
    search_fields = ("submission__id", "note")

    @admin.display(description="Requested by")
    def requested_by_admin(self, obj):
        return obj.requested_by_admin_label


@admin.register(VerificationRule)
class VerificationRuleAdmin(AppendOnlyAdmin):
    list_display = ("code", "title", "enabled", "risk_level", "second_approval_required")
    list_filter = ("enabled", "risk_level", "second_approval_required")
    search_fields = ("code", "title", "description")


@admin.register(ModerationRoleAssignment)
class ModerationRoleAssignmentAdmin(AppendOnlyAdmin):
    list_display = ("public_admin", "role", "assigned_at")
    list_filter = ("role",)
    search_fields = ("admin_number", "user__username", "user__email")

    @admin.display(description="Admin")
    def public_admin(self, obj):
        return obj.public_label


@admin.register(DogIdentityNumber)
class DogIdentityNumberAdmin(AppendOnlyAdmin):
    list_display = ("dog", "kind", "value", "created_at")
    search_fields = ("dog__name", "value")
