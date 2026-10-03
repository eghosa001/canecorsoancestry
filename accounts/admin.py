from django.contrib import admin

from .models import PaymentSubmissionLink, Profile, SubmissionPayment


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "display_name", "country")
    search_fields = ("user__username", "user__email", "display_name")


class PaymentSubmissionInline(admin.TabularInline):
    model = PaymentSubmissionLink
    extra = 0
    can_delete = False
    readonly_fields = ("submission", "slot_kind", "created_at")


@admin.register(SubmissionPayment)
class SubmissionPaymentAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "user",
        "kennel",
        "package",
        "amount_kobo",
        "status",
        "paid_at",
        "created_at",
    )
    list_filter = ("package", "status", "currency", "created_at")
    search_fields = ("reference", "user__username", "user__email", "kennel__name")
    readonly_fields = (
        "reference",
        "access_code",
        "authorization_url",
        "status",
        "paystack_transaction_id",
        "raw_response",
        "paid_at",
        "created_at",
        "updated_at",
    )
    inlines = (PaymentSubmissionInline,)


@admin.register(PaymentSubmissionLink)
class PaymentSubmissionLinkAdmin(admin.ModelAdmin):
    list_display = ("payment", "submission", "slot_kind", "created_at")
    list_filter = ("slot_kind", "created_at")
    search_fields = ("payment__reference", "submission__submitted_by__username")
    readonly_fields = ("payment", "submission", "slot_kind", "created_at")
