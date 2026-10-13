"""Private, pre-payment dog submissions; Paystack never bypasses moderation."""
import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from registry.models import Kennel, KennelMembership, Submission
from registry.verification import verify_submission

from .forms import DogSubmissionForm
from .models import PaymentSubmissionLink, SubmissionPayment
from .payments import PaystackError, initialize_transaction


def _editable_verified_kennels(user):
    return Kennel.objects.filter(
        memberships__user=user,
        memberships__role__in=(KennelMembership.Role.OWNER, KennelMembership.Role.EDITOR),
        verified_at__isnull=False,
    ).distinct()


@login_required
@require_http_methods(["GET", "POST"])
def create_dog_draft(request):
    """Keep the new dog off the public Dog table until paid and reviewed."""
    eligible_kennels = _editable_verified_kennels(request.user)
    form = DogSubmissionForm(
        request.POST or None,
        request.FILES or None,
        user=request.user,
    )
    form.fields["kennel"].queryset = eligible_kennels
    form.fields["kennel"].required = True
    if eligible_kennels.count() == 1:
        own_kennel = eligible_kennels.first()
        form.fields["kennel"].initial = own_kennel
        if own_kennel.is_public:
            form.fields["breeding_kennel"].initial = own_kennel

    if request.method == "POST" and form.is_valid():
        cleaned = form.cleaned_data
        kennel = cleaned["kennel"]
        photo = cleaned.get("primary_photo")
        from .views import _date_value, _upload_sha256, _add_upload_storage_error

        try:
            with transaction.atomic():
                submission = Submission.objects.create(
                    kind=Submission.Kind.DOG,
                    submitted_by=request.user,
                    kennel=kennel,
                    payload={
                        "_paid_submission": True,
                        "breeding_kennel_id": (
                            str(cleaned["breeding_kennel"].pk)
                            if cleaned.get("breeding_kennel") else None
                        ),
                        "name": cleaned["name"],
                        "sex": cleaned["sex"],
                        "date_of_birth": _date_value(cleaned["date_of_birth"]),
                        "colour": cleaned["colour"],
                        "country": cleaned["country"],
                        "bloodline": cleaned["bloodline"],
                        "sire_id": str(cleaned["sire"].pk) if cleaned["sire"] else None,
                        "dam_id": str(cleaned["dam"].pk) if cleaned["dam"] else None,
                        "registration": cleaned["registration"],
                        "microchip_number": cleaned["microchip_number"],
                        "litter_id": str(cleaned["litter"].pk) if cleaned["litter"] else None,
                        "bio": cleaned["bio"],
                        "photo_caption": cleaned.get("photo_caption", ""),
                        "photo_sha256": _upload_sha256(photo),
                    },
                    attachment=photo or "",
                    notes=cleaned["notes"],
                )
                verify_submission(submission)
        except (OSError, TimeoutError, ValueError) as exc:
            _add_upload_storage_error(form, "primary_photo", exc)
        else:
            messages.success(
                request,
                "Dog saved privately. Complete its listing payment and moderator review before publication.",
            )
            return redirect("accounts:submissions")

    return render(request, "accounts/submission_form.html", {
        "form": form,
        "eyebrow": "Private dog submission",
        "title": "Add a dog",
        "intro": (
            "Enter a new or previously unregistered dog. This creates a private "
            "submission, not a public pedigree. Pay the ₦500 listing fee from "
            "My submissions. Only an approved, paid dog can be published."
        ),
        "button_label": "Save dog privately",
        "multipart": True,
    })


@login_required
@require_http_methods(["GET", "POST"])
def draft_checkout(request, pk):
    """Assign one paid slot to the specific submitted dog, with no cross-account access."""
    submission = get_object_or_404(
        Submission.objects.select_related("kennel"),
        pk=pk,
        submitted_by=request.user,
        kind=Submission.Kind.DOG,
    )
    if (
        submission.status != Submission.Status.PENDING
        or not (submission.payload or {}).get("_paid_submission")
        or submission.kennel is None
        or not _editable_verified_kennels(request.user).filter(pk=submission.kennel_id).exists()
    ):
        raise PermissionDenied

    link = PaymentSubmissionLink.objects.select_related("payment").filter(
        submission=submission,
    ).first()
    if link and link.payment.status in (
        SubmissionPayment.Status.PENDING,
        SubmissionPayment.Status.PAID,
    ):
        return redirect("accounts:payment-detail", pk=link.payment_id)

    if request.method == "POST":
        if not settings.PAYSTACK_SECRET_KEY or not request.user.email:
            messages.error(request, "Paystack and an account email are required to start payment.")
            return redirect("accounts:draft-checkout", pk=pk)
        with transaction.atomic():
            locked = Submission.objects.select_for_update().get(pk=submission.pk)
            if locked.status != Submission.Status.PENDING:
                raise PermissionDenied
            previous = PaymentSubmissionLink.objects.select_for_update().select_related(
                "payment"
            ).filter(submission=locked).first()
            if previous and previous.payment.status in (
                SubmissionPayment.Status.PENDING,
                SubmissionPayment.Status.PAID,
            ):
                return redirect("accounts:payment-detail", pk=previous.payment_id)
            if previous:
                previous.delete()
            payment = SubmissionPayment(
                user=request.user,
                kennel=submission.kennel,
                package=SubmissionPayment.Package.SINGLE_DOG,
                dog_count=1,
                amount_kobo=SubmissionPayment.price_for(SubmissionPayment.Package.SINGLE_DOG),
                reference=f"CCA{uuid.uuid4().hex}",
            )
            payment.full_clean()
            payment.save()
            PaymentSubmissionLink.objects.create(
                submission=locked,
                payment=payment,
                slot_kind=PaymentSubmissionLink.SlotKind.DOG,
            )
            callback_url = f"{settings.SITE_URL}{reverse('accounts:paystack-callback')}"
            try:
                data = initialize_transaction(payment, callback_url)
            except PaystackError as exc:
                payment.status = SubmissionPayment.Status.FAILED
                payment.save(update_fields=("status", "updated_at"))
                messages.error(request, str(exc))
                return redirect("accounts:draft-checkout", pk=pk)
            payment.status = SubmissionPayment.Status.PENDING
            payment.access_code = data["access_code"]
            payment.authorization_url = data["authorization_url"]
            payment.save(update_fields=(
                "status", "access_code", "authorization_url", "updated_at",
            ))
        return redirect(f"{reverse('accounts:payment-detail', kwargs={'pk': payment.pk})}?checkout=1")

    return render(request, "accounts/draft_checkout.html", {
        "submission": submission,
        "price_naira": SubmissionPayment.price_for(SubmissionPayment.Package.SINGLE_DOG) // 100,
    })
