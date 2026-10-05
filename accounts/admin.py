from django import forms
from django.contrib import admin
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth import get_user_model

from .models import PaymentSubmissionLink, Profile, SubmissionPayment


class AdminEmailOrUsernameAuthenticationForm(AdminAuthenticationForm):
    username = forms.CharField(
        label="Email or username",
        widget=forms.TextInput(
            attrs={"autofocus": True, "autocomplete": "username"}
        ),
    )

    def clean(self):
        login_value = (self.cleaned_data.get("username") or "").strip()
        if "@" in login_value:
            user = (
                get_user_model()
                .objects.filter(email__iexact=login_value)
                .only("username")
                .first()
            )
            if user:
                self.cleaned_data["username"] = user.get_username()
        return super().clean()


admin.site.login_form = AdminEmailOrUsernameAuthenticationForm


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
        "user",
        "kennel",
        "package",
        "dog_count",
        "amount_kobo",
        "currency",
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

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PaymentSubmissionLink)
class PaymentSubmissionLinkAdmin(admin.ModelAdmin):
    list_display = ("payment", "submission", "slot_kind", "created_at")
    list_filter = ("slot_kind", "created_at")
    search_fields = ("payment__reference", "submission__submitted_by__username")
    readonly_fields = ("payment", "submission", "slot_kind", "created_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
