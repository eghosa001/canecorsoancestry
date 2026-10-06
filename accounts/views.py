import csv
import hashlib
import json
import logging
import urllib.error
from urllib.parse import urlparse
import uuid

from django.contrib import messages
from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import PasswordResetView
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Prefetch, Q
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from registry.data_quality import quick_quality_report
from registry.models import (
    DisputeCase,
    Dog,
    DogDocument,
    DogImage,
    DogSource,
    EvidenceRequest,
    Kennel,
    Litter,
    ModerationAudit,
    ModerationRoleAssignment,
    Notification,
    Submission,
    SubmissionEvidence,
    SubmissionReview,
    SubmissionRiskLevel,
    SubmissionVerificationStatus,
    VerificationEvent,
    VerificationFinding,
    VerificationRule,
)
from registry.permissions import (
    can_contribute_to_dog,
    can_contribute_to_kennel,
    can_edit_kennel,
    can_manage_verification,
    can_review_flagged_submissions,
    can_review_submissions,
    can_second_approve,
    admin_public_label,
    moderation_role,
)
from registry.services import (
    approve_submission,
    duplicate_candidates,
    duplicate_matches,
    merge_dogs,
    moderation_dog_search,
    record_audit,
    reject_high_risk_override,
    reject_submission,
    request_high_risk_override,
    request_submission_evidence,
    submission_diff,
)

from registry.verification import current_findings, verification_checklist, verify_submission

from pedigrees.services import pedigree_analysis, pedigree_export_rows

logger = logging.getLogger(__name__)


from .models import PaymentSubmissionLink, Profile, SubmissionPayment

from .forms import (
    BulkModerationForm,
    DisputeForm,
    DocumentVisibilityForm,
    DogCorrectionForm,
    DogDocumentSubmissionForm,
    DogImageSubmissionForm,
    DogSubmissionForm,
    DuplicateMatchForm,
    KennelClaimForm,
    KennelCreateForm,
    KennelEditForm,
    LitterPuppySubmissionForm,
    LitterSubmissionForm,
    MemberSignUpForm,
    PaymentPackageForm,
    MergeDogsForm,
    ReviewSubmissionForm,
    SubmissionEvidenceForm,
    VerificationEventForm,
    VerificationResendForm,
)

from .payments import (
    PaystackError,
    initialize_transaction,
    record_successful_payment,
    verify_transaction,
    webhook_signature_valid,
)


def _date_value(value):
    return value.isoformat() if value else ""


def _upload_sha256(upload):
    if not upload:
        return ""
    digest = hashlib.sha256()
    for chunk in upload.chunks():
        digest.update(chunk)
    upload.seek(0)
    return digest.hexdigest()


def _current_dog_photo_url(dog):
    """Return the same best available photo members see on the public profile."""
    managed = (
        DogImage.objects.filter(dog=dog)
        .order_by("-is_primary", "sort_order", "created_at")
        .first()
    )
    if managed and managed.image:
        return managed.image.url

    for source in DogSource.objects.filter(dog=dog).order_by(
        "-verified_at", "-created_at"
    ):
        payload = source.raw_payload if isinstance(source.raw_payload, dict) else {}
        image_url = str(payload.get("image_url") or "").strip()
        if not image_url:
            continue
        parsed = urlparse(image_url)
        if (
            parsed.scheme == "https"
            and parsed.hostname in {"canecorsopedigree.com", "www.canecorsopedigree.com"}
            and parsed.path.startswith("/static/images/animal/")
            and not parsed.username
            and not parsed.password
            and parsed.port in (None, 443)
        ):
            return image_url
    return ""


def _add_upload_storage_error(form, field_name, exc):
    logger.exception("member_upload_storage_failed field=%s error=%s", field_name, exc)
    form.add_error(
        field_name,
        "The file could not be stored right now. Please try again. Your other form details have been kept.",
    )


def _member_dogs(user):
    kennel_ids = user.kennel_memberships.values_list("kennel_id", flat=True)
    return Dog.objects.filter(
        Q(kennel_id__in=kennel_ids)
        | Q(
            submissions__kind=Submission.Kind.DOG,
            submissions__status=Submission.Status.APPROVED,
            submissions__submitted_by=user,
        )
    ).distinct()


def _send_verification_email(request, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    verify_path = reverse(
        "accounts:verify-email",
        kwargs={"uidb64": uid, "token": token},
    )
    verify_url = f"{settings.SITE_URL}{verify_path}"
    return send_mail(
        "Verify your Cane Corso Ancestry email",
        (
            "Confirm that this email belongs to your Cane Corso Ancestry account.\n\n"
            f"{verify_url}\n\n"
            "If you did not create this account, ignore this message."
        ),
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=False,
    )


class AccountPasswordResetView(PasswordResetView):
    """Do not pretend recovery email was sent when outbound mail is unavailable."""

    template_name = "registration/password_reset_form.html"
    email_template_name = "registration/password_reset_email.html"
    subject_template_name = "registration/password_reset_subject.txt"

    def form_valid(self, form):
        if not settings.ACCOUNT_EMAIL_ENABLED:
            form.add_error(
                None,
                "Password-reset email is temporarily unavailable. Please contact an administrator for account recovery.",
            )
            return self.form_invalid(form)
        return super().form_valid(form)


def signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    form = MemberSignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        verification_required = (
            settings.ACCOUNT_EMAIL_ENABLED
            and settings.REQUIRE_EMAIL_VERIFICATION
        )
        user = form.save(commit=False)
        user.is_active = not verification_required
        user.save()

        kennel_name = form.cleaned_data["kennel_name"]
        kennel_slug = slugify(kennel_name)[:190]
        Profile.objects.update_or_create(
            user=user,
            defaults={"display_name": kennel_name},
        )
        existing_kennel = Kennel.objects.filter(
            Q(name__iexact=kennel_name) | Q(slug__iexact=kennel_slug)
        ).first()
        if existing_kennel:
            submission, _ = Submission.objects.get_or_create(
                kind=Submission.Kind.KENNEL_CLAIM,
                status=Submission.Status.PENDING,
                submitted_by=user,
                kennel=existing_kennel,
                defaults={
                    "payload": {
                        "relationship": "Owner",
                        "signup_kennel_name": kennel_name,
                    },
                    "notes": "Kennel claim created automatically during account signup.",
                },
            )
        else:
            submission = Submission.objects.create(
                kind=Submission.Kind.KENNEL_CREATE,
                submitted_by=user,
                payload={"name": kennel_name, "slug": kennel_slug},
                notes="Kennel profile requested automatically during account signup.",
            )
        if submission.verification_status == SubmissionVerificationStatus.UNCHECKED:
            verify_submission(submission)

        if verification_required:
            try:
                sent = _send_verification_email(request, user)
            except Exception:
                logger.exception(
                    "member_verification_email_failed user_id=%s",
                    user.pk,
                )
                user.delete()
                form.add_error(
                    "email",
                    "We could not send the verification email. Please try again later.",
                )
            else:
                if not sent:
                    user.delete()
                    form.add_error(
                        "email",
                        "We could not send the verification email. Please try again later.",
                    )
                else:
                    return render(
                        request,
                        "registration/verification_sent.html",
                        {"email": user.email},
                    )
        else:
            login(request, user)
            messages.success(request, "Welcome to Cane Corso Ancestry.")
            return redirect("dashboard")

    return render(request, "registration/signup.html", {"form": form})


def verify_email(request, uidb64, token):
    user = None
    try:
        user_id = force_str(urlsafe_base64_decode(uidb64))
        user = get_user_model().objects.filter(pk=user_id).first()
    except (TypeError, ValueError, OverflowError):
        user = None

    if user and default_token_generator.check_token(user, token):
        if not user.is_active:
            user.is_active = True
            user.save(update_fields=("is_active",))
        login(request, user)
        messages.success(request, "Email verified. Your member account is active.")
        return redirect("dashboard")

    return render(request, "registration/verification_invalid.html", status=400)


def resend_verification(request):
    form = VerificationResendForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].strip().lower()
        user = get_user_model().objects.filter(
            email__iexact=email,
            is_active=False,
        ).first()
        if (
            user
            and settings.ACCOUNT_EMAIL_ENABLED
            and settings.REQUIRE_EMAIL_VERIFICATION
        ):
            try:
                _send_verification_email(request, user)
            except Exception:
                pass
        return render(
            request,
            "registration/verification_sent.html",
            {"email": email, "privacy_safe": True},
        )
    return render(
        request,
        "registration/resend_verification.html",
        {"form": form},
    )


@login_required
def submission_list(request):
    submissions = request.user.ancestry_submissions.select_related(
        "dog", "kennel", "litter", "document", "reviewed_by", "payment_link__payment"
    )
    paginator = Paginator(submissions, 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "accounts/submission_list.html",
        {
            "submissions": page_obj.object_list,
            "page_obj": page_obj,
        },
    )


@login_required
def submission_evidence_upload(request, pk):
    submission = get_object_or_404(
        Submission.objects.select_related("submitted_by", "dog", "kennel", "litter"),
        pk=pk,
        submitted_by=request.user,
    )
    if submission.status != Submission.Status.PENDING:
        messages.error(request, "Evidence can only be added while a submission is pending.")
        return redirect("accounts:submissions")

    open_request = submission.evidence_requests.filter(
        status=EvidenceRequest.Status.OPEN
    ).order_by("-created_at").first()
    form = SubmissionEvidenceForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        upload = form.cleaned_data["file"]
        digest = hashlib.sha256()
        for chunk in upload.chunks():
            digest.update(chunk)
        upload.seek(0)

        try:
            with transaction.atomic():
                evidence = SubmissionEvidence.objects.create(
                    submission=submission,
                    evidence_request=open_request,
                    evidence_type=form.cleaned_data["evidence_type"],
                    file=upload,
                    uploaded_by=request.user,
                    note=form.cleaned_data["note"],
                    sha256=digest.hexdigest(),
                )
                if open_request:
                    open_request.status = EvidenceRequest.Status.FULFILLED
                    open_request.fulfilled_at = timezone.now()
                    open_request.save(update_fields=("status", "fulfilled_at"))
                verify_submission(submission)
                record_audit(
                    action=ModerationAudit.Action.EVIDENCE_UPLOADED,
                    actor=request.user,
                    dog=submission.dog,
                    kennel=submission.kennel,
                    litter=submission.litter,
                    submission=submission,
                    summary={
                        "evidence_id": str(evidence.pk),
                        "evidence_type": evidence.evidence_type,
                        "sha256": evidence.sha256,
                        "private": True,
                    },
                    note=form.cleaned_data["note"],
                )
        except (OSError, urllib.error.URLError) as exc:
            _add_upload_storage_error(form, "file", exc)
        else:
            messages.success(
                request,
                "Verification evidence uploaded privately. It is not published on the public dog profile.",
            )
            return redirect("accounts:submissions")

    return render(
        request,
        "accounts/submission_form.html",
        {
            "form": form,
            "eyebrow": "Private verification evidence",
            "title": "Upload supporting evidence",
            "intro": (
                open_request.note
                if open_request
                else "This document is restricted to you and authorized reviewers unless a separate public-document submission is approved."
            ),
            "button_label": "Upload private evidence",
            "multipart": True,
        },
    )


@login_required
def submission_evidence_download(request, pk):
    evidence = get_object_or_404(
        SubmissionEvidence.objects.select_related("submission"),
        pk=pk,
    )
    if (
        evidence.submission.submitted_by_id != request.user.pk
        and not can_review_submissions(request.user)
    ):
        raise PermissionDenied
    if not evidence.file:
        raise PermissionDenied
    evidence.file.open("rb")
    filename = evidence.file.name.rsplit("/", 1)[-1]
    return FileResponse(evidence.file, as_attachment=True, filename=filename)


@login_required
def submit_dog(request):
    return redirect(f"{reverse('accounts:new-payment')}?package={SubmissionPayment.Package.SINGLE_DOG}")


@login_required
def new_payment(request):
    initial = {}
    requested_package = request.GET.get("package", "").strip()
    if requested_package in dict(SubmissionPayment.Package.choices):
        initial["package"] = requested_package

    form = PaymentPackageForm(
        request.POST or None,
        user=request.user,
        initial=initial,
    )
    verified_kennels = form.fields["kennel"].queryset
    recent_payments = request.user.ancestry_submission_payments.select_related(
        "kennel"
    )[:8]

    if request.method == "POST" and form.is_valid():
        if not settings.PAYSTACK_SECRET_KEY:
            form.add_error(None, "Paystack is not configured on the server yet.")
        elif not request.user.email:
            form.add_error(None, "Add an email address to your account before paying.")
        else:
            payment = SubmissionPayment(
                user=request.user,
                kennel=form.cleaned_data["kennel"],
                package=form.cleaned_data["package"],
                dog_count=form.cleaned_data["dog_count"],
                amount_kobo=form.cleaned_data["amount_kobo"],
                reference=f"CCA{uuid.uuid4().hex}",
            )
            payment.full_clean()
            payment.save()
            callback_url = f"{settings.SITE_URL}{reverse('accounts:paystack-callback')}"
            try:
                data = initialize_transaction(payment, callback_url)
            except PaystackError as exc:
                payment.status = SubmissionPayment.Status.FAILED
                payment.save(update_fields=("status", "updated_at"))
                form.add_error(None, str(exc))
            else:
                payment.status = SubmissionPayment.Status.PENDING
                payment.access_code = data["access_code"]
                payment.authorization_url = data["authorization_url"]
                payment.save(
                    update_fields=(
                        "status",
                        "access_code",
                        "authorization_url",
                        "updated_at",
                    )
                )
                return redirect(payment.authorization_url)

    return render(
        request,
        "accounts/payment_start.html",
        {
            "form": form,
            "recent_payments": recent_payments,
            "has_verified_kennel": verified_kennels.exists(),
            "paystack_configured": bool(settings.PAYSTACK_SECRET_KEY),
        },
    )


def _payment_for_member(request, pk):
    payment = get_object_or_404(
        SubmissionPayment.objects.select_related("kennel", "user"),
        pk=pk,
        user=request.user,
    )
    membership = request.user.kennel_memberships.filter(
        kennel=payment.kennel,
        role__in=["owner", "editor"],
    ).exists()
    if not membership or not payment.kennel.verified_at:
        raise PermissionDenied
    return payment


@login_required
def payment_detail(request, pk):
    payment = _payment_for_member(request, pk)
    links = list(
        payment.submission_links.select_related("submission").order_by("created_at")
    )
    dog_used = sum(
        1 for link in links if link.slot_kind == PaymentSubmissionLink.SlotKind.DOG
    )
    litter_link = next(
        (
            link
            for link in links
            if link.slot_kind == PaymentSubmissionLink.SlotKind.LITTER
        ),
        None,
    )
    paid = payment.status == SubmissionPayment.Status.PAID
    dog_limit = 1 if payment.package == SubmissionPayment.Package.SINGLE_DOG else payment.dog_count
    can_submit_dog = (
        paid
        and payment.package
        in {SubmissionPayment.Package.SINGLE_DOG, SubmissionPayment.Package.MULTI_DOG}
        and dog_used < dog_limit
    )
    can_submit_litter = (
        paid
        and payment.package == SubmissionPayment.Package.LITTER
        and litter_link is None
    )
    can_submit_puppy = (
        paid
        and payment.package == SubmissionPayment.Package.LITTER
        and litter_link is not None
        and litter_link.submission.status != Submission.Status.REJECTED
    )
    return render(
        request,
        "accounts/payment_detail.html",
        {
            "payment": payment,
            "links": links,
            "dog_used": dog_used,
            "litter_submission": litter_link.submission if litter_link else None,
            "can_submit_dog": can_submit_dog,
            "can_submit_litter": can_submit_litter,
            "can_submit_puppy": can_submit_puppy,
        },
    )


@login_required
def payment_submit_dog(request, pk):
    payment = _payment_for_member(request, pk)
    if payment.status != SubmissionPayment.Status.PAID:
        messages.error(request, "Complete the Paystack payment before submitting dogs.")
        return redirect("accounts:payment-detail", pk=payment.pk)
    if payment.package not in {
        SubmissionPayment.Package.SINGLE_DOG,
        SubmissionPayment.Package.MULTI_DOG,
    }:
        raise PermissionDenied

    form = DogSubmissionForm(
        request.POST or None,
        request.FILES or None,
        user=request.user,
        kennel=payment.kennel,
    )
    if request.method == "POST" and form.is_valid():
        cleaned = form.cleaned_data
        photo = cleaned.get("primary_photo")
        photo_sha256 = _upload_sha256(photo)
        try:
            with transaction.atomic():
                locked = SubmissionPayment.objects.select_for_update().get(pk=payment.pk)
                used = locked.submission_links.filter(
                    slot_kind=PaymentSubmissionLink.SlotKind.DOG
                ).count()
                limit = 1 if locked.package == SubmissionPayment.Package.SINGLE_DOG else locked.dog_count
                if used >= limit:
                    messages.error(request, "All dog slots in this payment package have been used.")
                    return redirect("accounts:payment-detail", pk=payment.pk)

                submission = Submission.objects.create(
                    kind=Submission.Kind.DOG,
                    submitted_by=request.user,
                    kennel=payment.kennel,
                    payload={
                        "_paid_submission": True,
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
                        "photo_sha256": photo_sha256,
                    },
                    attachment=photo or "",
                    notes=cleaned["notes"],
                )
                PaymentSubmissionLink.objects.create(
                    payment=locked,
                    submission=submission,
                    slot_kind=PaymentSubmissionLink.SlotKind.DOG,
                )
                verify_submission(submission)
        except (OSError, urllib.error.URLError) as exc:
            _add_upload_storage_error(form, "primary_photo", exc)
        else:
            messages.success(
                request,
                "Dog submitted with its photo for admin verification. It remains private until approval."
                if photo
                else "Dog submitted for admin verification. It remains private until approval.",
            )
            return redirect("accounts:payment-detail", pk=payment.pk)

    return render(
        request,
        "accounts/submission_form.html",
        {
            "form": form,
            "eyebrow": "Paid dog submission",
            "title": f"Submit a dog · {payment.kennel.name}",
            "intro": "Add the dog's details and, if available, its primary profile photo in this same submission. Nothing is published until an administrator approves it.",
            "button_label": "Submit for admin verification",
            "multipart": True,
        },
    )

@login_required
def payment_submit_litter(request, pk):
    payment = _payment_for_member(request, pk)
    if (
        payment.status != SubmissionPayment.Status.PAID
        or payment.package != SubmissionPayment.Package.LITTER
    ):
        raise PermissionDenied
    if payment.submission_links.filter(
        slot_kind=PaymentSubmissionLink.SlotKind.LITTER
    ).exists():
        messages.info(request, "This package already has a litter submission.")
        return redirect("accounts:payment-detail", pk=payment.pk)

    form = LitterSubmissionForm(
        request.POST or None,
        user=request.user,
        kennel=payment.kennel,
    )
    if request.method == "POST" and form.is_valid():
        if form.cleaned_data["kennel"] != payment.kennel:
            form.add_error("kennel", "This payment belongs to a different kennel.")
        else:
            with transaction.atomic():
                locked = SubmissionPayment.objects.select_for_update().get(pk=payment.pk)
                if locked.submission_links.filter(
                    slot_kind=PaymentSubmissionLink.SlotKind.LITTER
                ).exists():
                    messages.info(request, "This package already has a litter submission.")
                    return redirect("accounts:payment-detail", pk=payment.pk)
                cleaned = form.cleaned_data
                submission = Submission.objects.create(
                    kind=Submission.Kind.LITTER_CREATE,
                    submitted_by=request.user,
                    kennel=payment.kennel,
                    payload={
                        "_paid_submission": True,
                        "code": cleaned["code"],
                        "sire_id": str(cleaned["sire"].pk) if cleaned["sire"] else None,
                        "dam_id": str(cleaned["dam"].pk) if cleaned["dam"] else None,
                        "date_of_birth": _date_value(cleaned["date_of_birth"]),
                        "country": cleaned["country"],
                        "declared_puppy_count": cleaned["declared_puppy_count"],
                        "notes": cleaned["notes"],
                    },
                    notes=cleaned["review_notes"],
                )
                PaymentSubmissionLink.objects.create(
                    payment=locked,
                    submission=submission,
                    slot_kind=PaymentSubmissionLink.SlotKind.LITTER,
                )
                verify_submission(submission)
            messages.success(
                request,
                "Litter submitted for admin verification. You can now add puppies from this same litter.",
            )
            return redirect("accounts:payment-detail", pk=payment.pk)

    return render(
        request,
        "accounts/submission_form.html",
        {
            "form": form,
            "eyebrow": "Paid litter submission",
            "title": f"Submit a litter · {payment.kennel.name}",
            "intro": "The litter and its puppies remain private until an administrator verifies and approves the records.",
            "button_label": "Submit litter for admin verification",
        },
    )


@login_required
def payment_submit_puppy(request, pk):
    payment = _payment_for_member(request, pk)
    if (
        payment.status != SubmissionPayment.Status.PAID
        or payment.package != SubmissionPayment.Package.LITTER
    ):
        raise PermissionDenied
    litter_link = payment.submission_links.select_related("submission").filter(
        slot_kind=PaymentSubmissionLink.SlotKind.LITTER
    ).first()
    if litter_link is None or litter_link.submission.status == Submission.Status.REJECTED:
        messages.error(request, "Submit a valid litter first.")
        return redirect("accounts:payment-detail", pk=payment.pk)

    form = LitterPuppySubmissionForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        cleaned = form.cleaned_data
        photo = cleaned.get("primary_photo")
        photo_sha256 = _upload_sha256(photo)
        litter_submission = litter_link.submission
        litter_payload = litter_submission.payload or {}
        canonical_litter = litter_submission.litter
        litter_code = canonical_litter.code if canonical_litter else litter_payload.get("code")
        sire_id = canonical_litter.sire_id if canonical_litter else litter_payload.get("sire_id")
        dam_id = canonical_litter.dam_id if canonical_litter else litter_payload.get("dam_id")
        try:
            with transaction.atomic():
                locked = SubmissionPayment.objects.select_for_update().get(pk=payment.pk)
                submission = Submission.objects.create(
                    kind=Submission.Kind.DOG,
                    submitted_by=request.user,
                    kennel=payment.kennel,
                    payload={
                        "_paid_submission": True,
                        "litter_submission_id": str(litter_link.submission_id),
                        "litter_code": litter_code or "",
                        "sire_id": str(sire_id) if sire_id else None,
                        "dam_id": str(dam_id) if dam_id else None,
                        "name": cleaned["name"],
                        "sex": cleaned["sex"],
                        "date_of_birth": _date_value(cleaned["date_of_birth"]),
                        "colour": cleaned["colour"],
                        "country": cleaned["country"],
                        "bloodline": cleaned["bloodline"],
                        "registration": cleaned["registration"],
                        "microchip_number": cleaned["microchip_number"],
                        "bio": cleaned["bio"],
                        "photo_caption": cleaned.get("photo_caption", ""),
                        "photo_sha256": photo_sha256,
                    },
                    attachment=photo or "",
                    notes=cleaned["notes"],
                )
                PaymentSubmissionLink.objects.create(
                    payment=locked,
                    submission=submission,
                    slot_kind=PaymentSubmissionLink.SlotKind.PUPPY,
                )
                verify_submission(submission)
        except (OSError, urllib.error.URLError) as exc:
            _add_upload_storage_error(form, "primary_photo", exc)
        else:
            messages.success(
                request,
                "Puppy submitted with its photo for admin verification under this litter package."
                if photo
                else "Puppy submitted for admin verification under this litter package.",
            )
            return redirect("accounts:payment-detail", pk=payment.pk)

    return render(
        request,
        "accounts/submission_form.html",
        {
            "form": form,
            "eyebrow": "Litter puppy",
            "title": "Add a puppy from this litter",
            "intro": "Parentage, kennel and litter date are inherited from the litter. You can include the puppy's first profile photo now.",
            "button_label": "Submit puppy for admin verification",
            "multipart": True,
        },
    )

def paystack_callback(request):
    reference = (request.GET.get("reference") or request.GET.get("trxref") or "").strip()
    if not reference:
        return HttpResponse("Missing payment reference.", status=400)
    payment = SubmissionPayment.objects.filter(reference=reference).first()
    if payment is None:
        return HttpResponse("Unknown payment reference.", status=404)
    try:
        data = verify_transaction(reference)
        payment = record_successful_payment(reference, data)
    except PaystackError as exc:
        logger.warning("paystack_callback_failed reference=%s error=%s", reference, exc)
        if request.user.is_authenticated and request.user.pk == payment.user_id:
            messages.error(request, str(exc))
            return redirect("accounts:payment-detail", pk=payment.pk)
        return HttpResponse("Payment could not be verified.", status=400)

    if request.user.is_authenticated and request.user.pk == payment.user_id:
        messages.success(request, "Payment confirmed. Your submission package is ready.")
        return redirect("accounts:payment-detail", pk=payment.pk)
    next_url = reverse("accounts:payment-detail", kwargs={"pk": payment.pk})
    return redirect(f"{settings.LOGIN_URL}?next={next_url}")


@csrf_exempt
@require_POST
def paystack_webhook(request):
    signature = request.headers.get("x-paystack-signature", "")
    if not webhook_signature_valid(request.body, signature):
        return HttpResponse(status=400)
    try:
        event = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return HttpResponse(status=400)

    if event.get("event") == "charge.success":
        data = event.get("data") or {}
        reference = str(data.get("reference") or "")
        if reference and SubmissionPayment.objects.filter(reference=reference).exists():
            try:
                record_successful_payment(reference, data)
            except PaystackError:
                logger.exception("paystack_webhook_validation_failed reference=%s", reference)
                return HttpResponse(status=400)
    return HttpResponse(status=200)


@login_required
def submit_correction(request, pk):
    dog = get_object_or_404(Dog, pk=pk)
    if not can_contribute_to_dog(request.user, dog):
        raise PermissionDenied

    form = DogCorrectionForm(
        request.POST or None,
        instance=dog,
        user=request.user,
    )
    if request.method == "POST" and form.is_valid():
        cleaned = form.cleaned_data
        submission = Submission.objects.create(
            kind=Submission.Kind.CORRECTION,
            submitted_by=request.user,
            dog=dog,
            kennel=dog.kennel,
            payload={
                "name": cleaned["name"],
                "sex": cleaned["sex"],
                "date_of_birth": _date_value(cleaned["date_of_birth"]),
                "colour": cleaned["colour"],
                "country": cleaned["country"],
                "bloodline": cleaned["bloodline"],
                "sire_id": str(cleaned["sire"].pk) if cleaned["sire"] else None,
                "dam_id": str(cleaned["dam"].pk) if cleaned["dam"] else None,
                "litter_id": str(cleaned["litter"].pk) if cleaned["litter"] else None,
                "registration": cleaned["registration"],
                "microchip_number": cleaned["microchip_number"],
                "bio": cleaned["bio"],
            },
            notes=cleaned["notes"],
        )
        verify_submission(submission)
        messages.success(request, "Correction submitted for moderator review.")
        return redirect("accounts:submissions")

    return render(
        request,
        "accounts/submission_form.html",
        {
            "form": form,
            "eyebrow": "Correction",
            "title": f"Suggest changes to {dog.name}",
            "current_photo_url": _current_dog_photo_url(dog),
            "intro": "Your edit is reviewed before the canonical pedigree record changes.",
            "button_label": "Submit correction",
            "dog": dog,
        },
    )


@login_required
def submit_image(request, pk):
    dog = get_object_or_404(Dog, pk=pk)
    if not can_contribute_to_dog(request.user, dog):
        raise PermissionDenied

    form = DogImageSubmissionForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        upload = form.cleaned_data["attachment"]
        digest = hashlib.sha256()
        for chunk in upload.chunks():
            digest.update(chunk)
        upload.seek(0)
        try:
            with transaction.atomic():
                submission = Submission.objects.create(
                    kind=Submission.Kind.IMAGE,
                    submitted_by=request.user,
                    dog=dog,
                    kennel=dog.kennel,
                    payload={
                        "caption": form.cleaned_data["caption"],
                        "is_primary": form.cleaned_data["is_primary"],
                        "sha256": digest.hexdigest(),
                    },
                    attachment=upload,
                    notes=form.cleaned_data["notes"],
                )
        except (OSError, urllib.error.URLError) as exc:
            _add_upload_storage_error(form, "attachment", exc)
        else:
            verify_submission(submission)
            messages.success(request, "Photo submitted for review.")
            return redirect("accounts:submissions")

    return render(
        request,
        "accounts/submission_form.html",
        {
            "form": form,
            "eyebrow": "Dog media",
            "title": f"Submit a photo for {dog.name}",
            "current_photo_url": _current_dog_photo_url(dog),
            "intro": "Original uploads are retained; approved photos are attached to the canonical dog.",
            "button_label": "Submit photo",
            "multipart": True,
            "dog": dog,
        },
    )


@login_required
def submit_document(request, pk):
    dog = get_object_or_404(Dog, pk=pk)
    if not can_contribute_to_dog(request.user, dog):
        raise PermissionDenied

    form = DogDocumentSubmissionForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                submission = Submission.objects.create(
                    kind=Submission.Kind.DOCUMENT,
                    submitted_by=request.user,
                    dog=dog,
                    kennel=dog.kennel,
                    payload={
                        "title": form.cleaned_data["title"],
                        "document_type": form.cleaned_data["document_type"],
                        "is_public": form.cleaned_data["is_public"],
                    },
                    attachment=form.cleaned_data["attachment"],
                    notes=form.cleaned_data["notes"],
                )
        except (OSError, urllib.error.URLError) as exc:
            _add_upload_storage_error(form, "attachment", exc)
        else:
            verify_submission(submission)
            messages.success(request, "Document submitted for review.")
            return redirect("accounts:submissions")

    return render(
        request,
        "accounts/submission_form.html",
        {
            "form": form,
            "eyebrow": "Evidence",
            "title": f"Submit a document for {dog.name}",
            "current_photo_url": _current_dog_photo_url(dog),
            "intro": "Pedigree, health, DNA and external-registration evidence can be reviewed here.",
            "button_label": "Submit document",
            "multipart": True,
            "dog": dog,
        },
    )


@login_required
def submit_kennel(request):
    form = KennelCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        cleaned = form.cleaned_data
        from django.utils.text import slugify

        kennel_slug = slugify(cleaned["name"])[:190]
        submission = Submission.objects.create(
            kind=Submission.Kind.KENNEL_CREATE,
            submitted_by=request.user,
            payload={
                "name": cleaned["name"],
                "slug": kennel_slug,
                "country": cleaned["country"],
                "city": cleaned["city"],
                "website": cleaned["website"],
                "description": cleaned["description"],
            },
            notes=cleaned["notes"],
        )
        verify_submission(submission)
        messages.success(
            request,
            "Kennel profile submitted for fact-checking. The name is reserved while the submission is pending.",
        )
        return redirect("accounts:submissions")

    return render(
        request,
        "accounts/submission_form.html",
        {
            "form": form,
            "eyebrow": "Kennel identity",
            "title": "Create a kennel profile",
            "intro": "Kennel and breeder brand names are unique. New profiles are reviewed before they are created and linked to your account.",
            "button_label": "Submit kennel for review",
        },
    )


@login_required
def edit_kennel(request, pk):
    membership = request.user.kennel_memberships.select_related("kennel").filter(
        kennel_id=pk
    ).first()
    if not membership or not can_edit_kennel(request.user, membership.kennel):
        raise PermissionDenied
    kennel = membership.kennel

    form = KennelEditForm(request.POST or None, instance=kennel)
    if request.method == "POST" and form.is_valid():
        cleaned = form.cleaned_data
        submission = Submission.objects.create(
            kind=Submission.Kind.KENNEL,
            submitted_by=request.user,
            kennel=kennel,
            payload={
                "name": cleaned["name"],
                "country": cleaned["country"],
                "city": cleaned["city"],
                "description": cleaned["description"],
                "website": cleaned["website"],
            },
            notes=cleaned["notes"],
        )
        verify_submission(submission)
        messages.success(request, "Kennel changes submitted for review.")
        return redirect("accounts:submissions")

    return render(
        request,
        "accounts/submission_form.html",
        {
            "form": form,
            "eyebrow": "Kennel profile",
            "title": f"Edit {kennel.name}",
            "intro": "Owner/editor changes are reviewed before they replace the public kennel profile.",
            "button_label": "Submit kennel changes",
        },
    )


@login_required
def documents(request):
    memberships = request.user.kennel_memberships.select_related("kennel")
    kennel_ids = list(memberships.values_list("kennel_id", flat=True))
    editable_kennel_ids = {
        membership.kennel_id
        for membership in memberships
        if membership.role in {"owner", "editor"}
    }

    items = DogDocument.objects.filter(
        Q(submitted_by=request.user) | Q(dog__kennel_id__in=kennel_ids)
    ).select_related("dog__kennel", "submitted_by").distinct()

    document_type = request.GET.get("type", "").strip()
    visibility = request.GET.get("visibility", "").strip()
    if document_type:
        items = items.filter(document_type=document_type)
    if visibility == "public":
        items = items.filter(is_public=True)
    elif visibility == "private":
        items = items.filter(is_public=False)

    paginator = Paginator(items, 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    visible_items = page_obj.object_list
    pending_visibility_ids = set(
        Submission.objects.filter(
            kind=Submission.Kind.DOCUMENT_VISIBILITY,
            status=Submission.Status.PENDING,
            document__in=visible_items,
        ).values_list("document_id", flat=True)
    )
    query_params = request.GET.copy()
    query_params.pop("page", None)
    return render(
        request,
        "accounts/documents.html",
        {
            "documents": visible_items,
            "page_obj": page_obj,
            "querystring": query_params.urlencode(),
            "document_types": DogDocument.DocumentType.choices,
            "selected_type": document_type,
            "selected_visibility": visibility,
            "pending_visibility_ids": pending_visibility_ids,
            "editable_kennel_ids": editable_kennel_ids,
        },
    )


@login_required
def notifications(request):
    if request.method == "POST":
        request.user.ancestry_notifications.filter(read_at__isnull=True).update(
            read_at=timezone.now()
        )
        return redirect("accounts:notifications")
    items = request.user.ancestry_notifications.all()
    paginator = Paginator(items, 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "accounts/notifications.html",
        {
            "notifications": page_obj.object_list,
            "page_obj": page_obj,
        },
    )


@login_required
def moderation_queue(request):
    if not can_review_submissions(request.user):
        raise PermissionDenied

    pending = (
        Submission.objects.filter(status=Submission.Status.PENDING)
        .select_related(
            "submitted_by",
            "dog",
            "kennel",
            "litter",
            "document",
            "assigned_to",
            "payment_link__payment",
        )
        .prefetch_related(
            Prefetch(
                "verification_findings",
                queryset=VerificationFinding.objects.filter(is_current=True).select_related("rule"),
                to_attr="current_verification_findings",
            )
        )
    )

    query = request.GET.get("q", "").strip()
    kind = request.GET.get("kind", "").strip()
    priority = request.GET.get("priority", "").strip()
    assignment = request.GET.get("assignment", "").strip()
    risk = request.GET.get("risk", "").strip()

    if query:
        pending = pending.filter(
            Q(submitted_by__username__icontains=query)
            | Q(dog__name__icontains=query)
            | Q(kennel__name__icontains=query)
            | Q(litter__code__icontains=query)
            | Q(document__title__icontains=query)
            | Q(notes__icontains=query)
        ).distinct()
    if kind in dict(Submission.Kind.choices):
        pending = pending.filter(kind=kind)
    if priority.isdigit() and int(priority) in dict(Submission.Priority.choices):
        pending = pending.filter(priority=int(priority))
    if risk in dict(SubmissionRiskLevel.choices):
        pending = pending.filter(risk_level=risk)
    if assignment == "mine":
        pending = pending.filter(assigned_to=request.user)
    elif assignment == "unassigned":
        pending = pending.filter(assigned_to__isnull=True)

    pending = pending.order_by("-priority", "-risk_level", "created_at")
    paginator = Paginator(pending, 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    pending_items = list(page_obj.object_list)
    query_params = request.GET.copy()
    query_params.pop("page", None)

    dog_reference_ids = set()
    litter_reference_ids = set()
    for item in pending_items:
        payload = item.payload or {}
        for key in ("sire_id", "dam_id"):
            value = payload.get(key)
            if not value:
                continue
            try:
                dog_reference_ids.add(uuid.UUID(str(value)))
            except (TypeError, ValueError, AttributeError):
                pass
        value = payload.get("litter_id")
        if value:
            try:
                litter_reference_ids.add(uuid.UUID(str(value)))
            except (TypeError, ValueError, AttributeError):
                pass

    dog_names = {
        str(pk): name
        for pk, name in Dog.objects.filter(pk__in=dog_reference_ids).values_list("pk", "name")
    }
    litter_names = {
        str(pk): code
        for pk, code in Litter.objects.filter(pk__in=litter_reference_ids).values_list("pk", "code")
    }

    for item in pending_items:
        item.review_diff = submission_diff(
            item,
            dog_names=dog_names,
            litter_names=litter_names,
        )
        item.current_findings = [
            finding
            for finding in getattr(item, "current_verification_findings", ())
            if finding.risk_level != SubmissionRiskLevel.GREEN
        ]
        age_days = max(0, (timezone.now() - item.created_at).days)
        item.age_days = age_days
        item.is_aging = age_days >= 7

    duplicate_form = DuplicateMatchForm(request.GET or None)
    duplicate_lookup_results = []
    duplicate_results = []
    duplicate_reference = None
    reference_id = request.GET.get("reference", "").strip()
    duplicate_query = request.GET.get("duplicate_q", "").strip()
    duplicate_scan_loaded = request.GET.get("duplicate_scan") == "1"

    if reference_id:
        try:
            parsed_reference_id = uuid.UUID(reference_id)
        except (TypeError, ValueError):
            messages.error(request, "That duplicate-reference ID is invalid.")
        else:
            duplicate_reference = (
                Dog.objects.select_related("kennel", "sire", "dam")
                .prefetch_related("registrations")
                .filter(pk=parsed_reference_id)
                .first()
            )
            if duplicate_reference:
                duplicate_results = duplicate_matches(duplicate_reference)
    elif duplicate_query and duplicate_form.is_valid():
        duplicate_lookup_results = moderation_dog_search(
            duplicate_form.cleaned_data["duplicate_q"]
        )

    automatic_duplicate_candidates = (
        duplicate_candidates() if duplicate_scan_loaded else []
    )

    disputes = list(
        DisputeCase.objects.filter(
            status__in=[DisputeCase.Status.OPEN, DisputeCase.Status.REVIEWING]
        )
        .select_related("dog", "opened_by", "assigned_to")
        .order_by("status", "created_at")[:50]
    )

    assignee_ids = {
        obj.assigned_to_id
        for obj in [*pending_items, *disputes]
        if obj.assigned_to_id
    }
    assignee_labels = {
        assignment.user_id: assignment.public_label
        for assignment in ModerationRoleAssignment.objects.filter(
            user_id__in=assignee_ids
        ).only("user_id", "admin_number")
    }
    for obj in [*pending_items, *disputes]:
        obj.queue_assignee_label = (
            assignee_labels.get(obj.assigned_to_id, "Admin")
            if obj.assigned_to_id
            else ""
        )

    return render(
        request,
        "accounts/moderation_queue.html",
        {
            "pending": pending_items,
            "pending_total": paginator.count,
            "page_obj": page_obj,
            "querystring": query_params.urlencode(),
            "merge_form": MergeDogsForm(),
            "verification_form": VerificationEventForm(),
            "duplicate_candidates": automatic_duplicate_candidates,
            "duplicate_scan_loaded": duplicate_scan_loaded,
            "duplicate_form": duplicate_form,
            "duplicate_reference": duplicate_reference,
            "duplicate_lookup_results": duplicate_lookup_results,
            "duplicate_results": duplicate_results,
            "bulk_form": BulkModerationForm(),
            "disputes": disputes,
            "can_manage_verification": can_manage_verification(request.user),
            "filters": {
                "q": query,
                "kind": kind,
                "priority": priority,
                "assignment": assignment,
                "risk": risk,
            },
            "submission_kinds": Submission.Kind.choices,
            "priority_choices": Submission.Priority.choices,
            "risk_choices": SubmissionRiskLevel.choices,
        },
    )


@login_required
def moderation_submission_detail(request, pk):
    if not can_review_submissions(request.user):
        raise PermissionDenied

    submission = get_object_or_404(
        Submission.objects.select_related(
            "submitted_by",
            "dog",
            "kennel",
            "litter",
            "document",
            "assigned_to",
            "reviewed_by",
            "payment_link__payment",
        ),
        pk=pk,
    )
    if submission.verification_status == SubmissionVerificationStatus.UNCHECKED:
        verify_submission(submission)
        submission.refresh_from_db()

    findings = list(current_findings(submission))
    blocking_findings = [
        finding
        for finding in findings
        if finding.risk_level != SubmissionRiskLevel.GREEN
    ]
    check_rows = verification_checklist(submission)

    litter_submission = None
    if submission.kind == Submission.Kind.LITTER_CREATE:
        litter_submission = submission
    else:
        litter_submission_id = (submission.payload or {}).get("litter_submission_id")
        if litter_submission_id:
            try:
                parsed_litter_submission_id = uuid.UUID(str(litter_submission_id))
            except (TypeError, ValueError, AttributeError):
                parsed_litter_submission_id = None
            if parsed_litter_submission_id:
                litter_submission = (
                    Submission.objects.select_related("litter", "kennel")
                    .filter(
                        pk=parsed_litter_submission_id,
                        kind=Submission.Kind.LITTER_CREATE,
                    )
                    .first()
                )

    litter_members = []
    if litter_submission is not None:
        litter_members = list(
            Submission.objects.filter(
                kind=Submission.Kind.DOG,
                payload__litter_submission_id=str(litter_submission.pk),
            )
            .select_related("dog", "submitted_by")
            .order_by("created_at")
        )
        for member in litter_members:
            member.submitted_name = str((member.payload or {}).get("name") or "").strip()
            member.submitted_sex = str((member.payload or {}).get("sex") or "").strip()
            member.submitted_dob = str((member.payload or {}).get("date_of_birth") or "").strip()

    evidence_requests = list(
        submission.evidence_requests.select_related("requested_by").all()
    )
    evidence = list(
        submission.verification_evidence.select_related(
            "uploaded_by", "evidence_request"
        ).all()
    )
    reviews = list(
        submission.review_decisions.select_related("reviewer").all()
    )
    audit_events = list(
        submission.audit_events.select_related("actor").order_by("-created_at")
    )
    pending_override = None
    if submission.verification_status == SubmissionVerificationStatus.AWAITING_SECOND:
        pending_override = (
            submission.review_decisions.filter(
                action=SubmissionReview.Action.OVERRIDE_REQUESTED
            )
            .select_related("reviewer")
            .order_by("-created_at")
            .first()
        )

    return render(
        request,
        "accounts/moderation_submission_detail.html",
        {
            "submission": submission,
            "findings": findings,
            "blocking_findings": blocking_findings,
            "check_rows": check_rows,
            "litter_submission": litter_submission,
            "litter_members": litter_members,
            "review_diff": submission_diff(submission),
            "evidence_requests": evidence_requests,
            "evidence": evidence,
            "reviews": reviews,
            "audit_events": audit_events,
            "pending_override": pending_override,
            "can_review_flagged": can_review_flagged_submissions(request.user),
            "can_second_approve": bool(
                pending_override
                and pending_override.reviewer_id != request.user.pk
                and can_second_approve(request.user)
            ),
            "reviewer_role": moderation_role(request.user),
        },
    )


@login_required
def review_submission(request, pk, decision):
    if request.method != "POST":
        return redirect("accounts:moderation")
    if not can_review_submissions(request.user):
        raise PermissionDenied

    submission = get_object_or_404(Submission, pk=pk)
    if submission.verification_status == SubmissionVerificationStatus.UNCHECKED:
        verify_submission(submission)
        submission.refresh_from_db()

    form = ReviewSubmissionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Review note was invalid.")
        return redirect("accounts:moderation-submission", pk=submission.pk)

    notes = form.cleaned_data["resolution_notes"].strip()
    findings = list(current_findings(submission))
    flagged = any(
        finding.risk_level != SubmissionRiskLevel.GREEN
        for finding in findings
    )
    try:
        if decision == "approve":
            if flagged:
                raise ValueError(
                    "This submission has automated warnings. Use Approve with override so the reason is preserved."
                )
            approve_submission(submission, request.user, notes)
            messages.success(request, "Submission approved.")

        elif decision == "reject":
            if flagged and not can_review_flagged_submissions(request.user):
                raise ValueError(
                    "A senior reviewer or owner must decide a flagged submission."
                )
            reject_submission(submission, request.user, notes)
            messages.success(request, "Submission rejected.")

        elif decision == "request_evidence":
            request_submission_evidence(submission, request.user, notes)
            messages.success(request, "Evidence requested from the submitting member.")

        elif decision == "override":
            if not can_review_flagged_submissions(request.user):
                raise ValueError(
                    "Only a senior reviewer or owner can override an automated warning."
                )
            if not flagged:
                raise ValueError("There is no current warning to override.")
            if submission.requires_second_review:
                request_high_risk_override(submission, request.user, notes)
                messages.success(
                    request,
                    "High-risk override recorded. A different senior reviewer or owner must approve it before publication.",
                )
            else:
                approve_submission(
                    submission,
                    request.user,
                    notes,
                    allow_override=True,
                )
                messages.success(request, "Submission approved with a recorded override.")

        elif decision == "second_approve":
            if not can_second_approve(request.user):
                raise ValueError(
                    "Only a senior reviewer or owner can complete second review."
                )
            override_review = (
                submission.review_decisions.filter(
                    action=SubmissionReview.Action.OVERRIDE_REQUESTED
                )
                .order_by("-created_at")
                .first()
            )
            if override_review is None:
                raise ValueError("No high-risk override is awaiting second review.")
            approve_submission(
                submission,
                request.user,
                notes,
                allow_override=True,
                override_review=override_review,
            )
            messages.success(request, "Second approval completed. Submission published.")

        elif decision == "second_reject":
            reject_high_risk_override(submission, request.user, notes)
            messages.success(
                request,
                "Second reviewer declined the override. The submission remains pending for review.",
            )
        else:
            messages.error(request, "Unknown review action.")

    except (ValueError, ValidationError, IntegrityError) as exc:
        messages.error(request, str(exc))

    if Submission.objects.filter(pk=submission.pk, status=Submission.Status.PENDING).exists():
        return redirect("accounts:moderation-submission", pk=submission.pk)
    return redirect("accounts:moderation")


@login_required
def merge_dogs_view(request):
    if not can_review_flagged_submissions(request.user):
        raise PermissionDenied
    if request.method != "POST":
        return redirect("accounts:moderation")
    form = MergeDogsForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Choose two different dog records.")
        return redirect("accounts:moderation")

    canonical = form.cleaned_data["canonical"]
    duplicate = form.cleaned_data["duplicate"]
    try:
        history = merge_dogs(canonical, duplicate, performed_by=request.user)
    except (ValueError, ValidationError, IntegrityError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            f"Merged {history.retired_name} into {history.canonical_dog.name}.",
        )
    return redirect("accounts:moderation")



@login_required
def verify_dog(request):
    if not can_review_submissions(request.user):
        raise PermissionDenied
    if request.method != "POST":
        return redirect("accounts:moderation")
    form = VerificationEventForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Verification details were invalid.")
        return redirect("accounts:moderation")

    dog = form.cleaned_data["dog"]
    state = form.cleaned_data["state"]
    field_name = form.cleaned_data["field_name"].strip()
    source = form.cleaned_data["source"]
    event = VerificationEvent.objects.create(
        dog=dog,
        field_name=field_name,
        state=state,
        source=source,
        reviewer=request.user,
        note=form.cleaned_data["note"],
    )
    if source and not source.verified_at:
        source.verified_at = timezone.now()
        source.save(update_fields=("verified_at",))
    if not field_name:
        dog.verification_state = state
        dog.save(update_fields=("verification_state", "updated_at"))
    record_audit(
        action=ModerationAudit.Action.VERIFICATION,
        actor=request.user,
        dog=dog,
        kennel=dog.kennel,
        summary={
            "verification_event_id": event.pk,
            "field_name": field_name,
            "state": state,
        },
        note=form.cleaned_data["note"],
    )
    messages.success(request, "Verification event recorded.")
    return redirect("accounts:moderation")



@login_required
def my_pedigrees(request):
    dogs = _member_dogs(request.user).select_related(
        "kennel", "sire", "dam"
    ).order_by("name")
    paginator = Paginator(dogs, 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    rows = [
        {
            "dog": dog,
            "parent_count": int(bool(dog.sire_id)) + int(bool(dog.dam_id)),
        }
        for dog in page_obj.object_list
    ]
    return render(
        request,
        "accounts/my_pedigrees.html",
        {"rows": rows, "page_obj": page_obj},
    )


@login_required
def member_pedigree_detail(request, pk):
    dog = get_object_or_404(
        _member_dogs(request.user).select_related("kennel", "sire", "dam"),
        pk=pk,
    )
    try:
        requested = int(request.GET.get("generations", "4"))
    except ValueError:
        requested = 4
    generations = requested if requested in {4, 6, 8, 10} else 4
    analysis = pedigree_analysis(dog, generations, public_only=False)

    return render(
        request,
        "accounts/member_pedigree_detail.html",
        {
            "dog": dog,
            "generations": generations,
            "generation_options": (4, 6, 8, 10),
            "analysis": analysis,
            "layers": analysis["layers"],
            "repeated": analysis["repeated"],
            "coi_percent": analysis["coi_percent"],
            "cycle_error": analysis["cycle_error"],
            "member_mode": True,
        },
    )


@login_required
def member_pedigree_export(request, pk):
    dog = get_object_or_404(
        _member_dogs(request.user).select_related("kennel"),
        pk=pk,
    )
    try:
        requested = int(request.GET.get("generations", "4"))
    except ValueError:
        requested = 4
    generations = requested if requested in {4, 6, 8, 10} else 4

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="{dog.slug}-pedigree-{generations}g.csv"'
    )
    writer = csv.DictWriter(
        response,
        fieldnames=(
            "generation",
            "path",
            "dog_id",
            "name",
            "sex",
            "date_of_birth",
            "colour",
            "country",
            "kennel",
            "repeated",
            "path_contribution_percent",
        ),
    )
    writer.writeheader()
    writer.writerows(pedigree_export_rows(dog, generations, public_only=False))
    return response


@login_required
def my_litters(request):
    memberships = request.user.kennel_memberships.select_related("kennel")
    kennel_ids = list(memberships.values_list("kennel_id", flat=True))
    editable_kennel_ids = {
        membership.kennel_id
        for membership in memberships
        if membership.role in {"owner", "editor"}
    }
    litters = (
        Litter.objects.filter(kennel_id__in=kennel_ids)
        .select_related("kennel", "sire", "dam")
        .order_by("-date_of_birth", "code")
    )
    paginator = Paginator(litters, 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "accounts/my_litters.html",
        {
            "litters": page_obj.object_list,
            "page_obj": page_obj,
            "editable_kennel_ids": editable_kennel_ids,
            "can_create_litter": bool(editable_kennel_ids),
        },
    )


@login_required
def submit_litter(request):
    return redirect(f"{reverse('accounts:new-payment')}?package={SubmissionPayment.Package.LITTER}")


@login_required
def edit_litter(request, pk):
    litter = get_object_or_404(Litter.objects.select_related("kennel"), pk=pk)
    if not can_edit_kennel(request.user, litter.kennel):
        raise PermissionDenied

    form = LitterSubmissionForm(
        request.POST or None,
        user=request.user,
        kennel=litter.kennel,
        litter=litter,
    )
    if request.method == "POST" and form.is_valid():
        cleaned = form.cleaned_data
        if cleaned["kennel"] != litter.kennel:
            form.add_error("kennel", "An existing litter cannot be moved to another kennel.")
        else:
            submission = Submission.objects.create(
                kind=Submission.Kind.LITTER_EDIT,
                submitted_by=request.user,
                kennel=litter.kennel,
                litter=litter,
                payload={
                    "code": cleaned["code"],
                    "sire_id": str(cleaned["sire"].pk) if cleaned["sire"] else None,
                    "dam_id": str(cleaned["dam"].pk) if cleaned["dam"] else None,
                    "date_of_birth": _date_value(cleaned["date_of_birth"]),
                    "country": cleaned["country"],
                    "declared_puppy_count": cleaned["declared_puppy_count"],
                    "notes": cleaned["notes"],
                },
                notes=cleaned["review_notes"],
            )
            verify_submission(submission)
            messages.success(request, "Litter changes submitted for moderator review.")
            return redirect("accounts:submissions")

    return render(
        request,
        "accounts/submission_form.html",
        {
            "form": form,
            "eyebrow": "Litter management",
            "title": f"Suggest changes to {litter.code}",
            "intro": "The public/canonical litter stays unchanged until a moderator approves the correction.",
            "button_label": "Submit litter changes",
        },
    )


@login_required
def claim_kennel(request, pk):
    kennel = get_object_or_404(Kennel, pk=pk)
    if request.user.kennel_memberships.filter(kennel=kennel).exists():
        messages.info(request, "Your account is already linked to this kennel.")
        return redirect("dashboard")
    if kennel.memberships.exists():
        messages.error(
            request,
            "This kennel is already linked to an account. Ownership changes require moderator assistance.",
        )
        return redirect("registry:kennel-detail", slug=kennel.slug)

    pending_claim = Submission.objects.filter(
        kind=Submission.Kind.KENNEL_CLAIM,
        status=Submission.Status.PENDING,
        kennel=kennel,
    ).select_related("submitted_by").first()
    if pending_claim:
        if pending_claim.submitted_by_id == request.user.id:
            messages.info(request, "You already have a pending ownership claim for this kennel.")
        else:
            messages.error(
                request,
                "This kennel already has an ownership claim under review. A second claim cannot be opened until that review is resolved.",
            )
        return redirect("accounts:submissions")

    form = KennelClaimForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                submission = Submission.objects.create(
                    kind=Submission.Kind.KENNEL_CLAIM,
                    submitted_by=request.user,
                    kennel=kennel,
                    payload={"relationship": form.cleaned_data["relationship"]},
                    attachment=form.cleaned_data["evidence"] or "",
                    notes=form.cleaned_data["notes"],
                )
        except (OSError, urllib.error.URLError) as exc:
            _add_upload_storage_error(form, "evidence", exc)
        else:
            verify_submission(submission)
            messages.success(request, "Kennel ownership claim submitted for review.")
            return redirect("accounts:submissions")

    return render(
        request,
        "accounts/submission_form.html",
        {
            "form": form,
            "eyebrow": "Kennel ownership",
            "title": f"Claim {kennel.name}",
            "intro": "A moderator will verify your relationship to this kennel before owner access is granted.",
            "button_label": "Submit ownership claim",
            "multipart": True,
        },
    )


@login_required
def request_document_visibility(request, pk):
    document = get_object_or_404(
        DogDocument.objects.select_related("dog__kennel"),
        pk=pk,
    )
    if not can_edit_kennel(request.user, document.dog.kennel):
        raise PermissionDenied

    initial = {"is_public": document.is_public}
    form = DocumentVisibilityForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        desired = form.cleaned_data["is_public"]
        if desired == document.is_public:
            messages.info(request, "The document already has that visibility.")
            return redirect("accounts:documents")
        pending = Submission.objects.filter(
            kind=Submission.Kind.DOCUMENT_VISIBILITY,
            status=Submission.Status.PENDING,
            document=document,
        ).exists()
        if pending:
            messages.info(request, "A visibility request for this document is already pending.")
            return redirect("accounts:documents")

        submission = Submission.objects.create(
            kind=Submission.Kind.DOCUMENT_VISIBILITY,
            submitted_by=request.user,
            dog=document.dog,
            kennel=document.dog.kennel,
            document=document,
            payload={"is_public": desired},
            notes=form.cleaned_data["notes"],
        )
        verify_submission(submission)
        messages.success(request, "Document visibility change submitted for review.")
        return redirect("accounts:submissions")

    return render(
        request,
        "accounts/submission_form.html",
        {
            "form": form,
            "eyebrow": "Document management",
            "title": f"Visibility · {document.title}",
            "intro": "Public/private visibility changes are moderated so evidence is not exposed accidentally.",
            "button_label": "Submit visibility request",
        },
    )



@login_required
def open_dispute(request, pk):
    kennel_ids = request.user.kennel_memberships.values_list("kennel_id", flat=True)
    dog = get_object_or_404(
        Dog.objects.filter(Q(is_public=True) | Q(kennel_id__in=kennel_ids)).distinct(),
        pk=pk,
    )
    form = DisputeForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                dispute = DisputeCase.objects.create(
                    dog=dog,
                    opened_by=request.user,
                    reason=form.cleaned_data["reason"],
                    details=form.cleaned_data["details"],
                    attachment=form.cleaned_data["attachment"] or "",
                )
        except (OSError, urllib.error.URLError) as exc:
            _add_upload_storage_error(form, "attachment", exc)
        else:
            record_audit(
                action=ModerationAudit.Action.DISPUTE_OPENED,
                actor=request.user,
                dog=dog,
                kennel=dog.kennel,
                dispute=dispute,
                summary={"reason": dispute.reason},
            )
            messages.success(request, "Review case opened. A moderator can now investigate it.")
            return redirect("accounts:my-disputes")

    return render(
        request,
        "accounts/submission_form.html",
        {
            "form": form,
            "eyebrow": "Dispute / review case",
            "title": f"Request review · {dog.name}",
            "intro": "Report a specific pedigree, identity, health, ownership or duplicate concern. Opening a case does not alter the canonical record.",
            "button_label": "Open review case",
            "multipart": True,
        },
    )


@login_required
def my_disputes(request):
    disputes = request.user.opened_ancestry_disputes.select_related(
        "dog", "assigned_to", "closed_by"
    )
    paginator = Paginator(disputes, 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    visible_disputes = list(page_obj.object_list)
    assignee_ids = {
        dispute.assigned_to_id
        for dispute in visible_disputes
        if dispute.assigned_to_id
    }
    assignee_labels = {
        assignment.user_id: assignment.public_label
        for assignment in ModerationRoleAssignment.objects.filter(
            user_id__in=assignee_ids
        ).only("user_id", "admin_number")
    }
    for dispute in visible_disputes:
        dispute.member_assignee_label = (
            assignee_labels.get(dispute.assigned_to_id, "Admin")
            if dispute.assigned_to_id
            else ""
        )
    return render(
        request,
        "accounts/my_disputes.html",
        {
            "disputes": visible_disputes,
            "page_obj": page_obj,
        },
    )


@login_required
def bulk_moderation(request):
    if not can_review_submissions(request.user):
        raise PermissionDenied
    if request.method != "POST":
        return redirect("accounts:moderation")

    form = BulkModerationForm(request.POST)
    submission_ids = request.POST.getlist("submission_ids")
    if not form.is_valid() or not submission_ids:
        messages.error(request, "Select at least one pending submission and a valid bulk action.")
        return redirect("accounts:moderation")

    parsed_submission_ids = []
    try:
        parsed_submission_ids = [uuid.UUID(str(value)) for value in submission_ids]
    except (TypeError, ValueError, AttributeError):
        messages.error(request, "One or more selected submission IDs are invalid.")
        return redirect("accounts:moderation")

    action = form.cleaned_data["action"]
    note = form.cleaned_data["resolution_notes"].strip()
    now = timezone.now()

    with transaction.atomic():
        queryset = Submission.objects.select_for_update().filter(
            pk__in=parsed_submission_ids,
            status=Submission.Status.PENDING,
        )
        items = list(queryset)
        if not items:
            messages.info(request, "None of the selected submissions are still pending.")
            return redirect("accounts:moderation")

        if action == "reject":
            for item in items:
                reject_submission(item, request.user, note)
        elif action == "assign_me":
            queryset.update(
                assigned_to=request.user,
                review_started_at=now,
                updated_at=now,
            )
        elif action == "unassign":
            queryset.update(
                assigned_to=None,
                review_started_at=None,
                updated_at=now,
            )
        else:
            priority_map = {
                "priority_low": Submission.Priority.LOW,
                "priority_normal": Submission.Priority.NORMAL,
                "priority_high": Submission.Priority.HIGH,
                "priority_urgent": Submission.Priority.URGENT,
            }
            new_priority = priority_map.get(action)
            if new_priority is None:
                messages.error(request, "Unsupported bulk moderation action.")
                return redirect("accounts:moderation")
            queryset.update(priority=new_priority, updated_at=now)

        if action != "reject":
            record_audit(
                action=ModerationAudit.Action.SUBMISSION_BULK,
                actor=request.user,
                summary={
                    "action": action,
                    "count": len(items),
                    "submission_ids": [str(item.pk) for item in items],
                },
                note=note,
            )

    messages.success(request, f"Bulk moderation updated {len(items)} submission(s).")
    return redirect("accounts:moderation")


@login_required
def review_dispute(request, pk, decision):
    if not can_review_submissions(request.user):
        raise PermissionDenied
    if request.method != "POST":
        return redirect("accounts:moderation")

    note = request.POST.get("resolution_notes", "").strip()
    with transaction.atomic():
        dispute = get_object_or_404(
            DisputeCase.objects.select_for_update().select_related("dog", "opened_by"),
            pk=pk,
        )

        if decision == "assign":
            dispute.assigned_to = request.user
            dispute.status = DisputeCase.Status.REVIEWING
        elif decision == "resolve":
            if not note:
                messages.error(request, "A resolution note is required.")
                return redirect("accounts:moderation")
            dispute.status = DisputeCase.Status.RESOLVED
            dispute.resolution_notes = note
            dispute.closed_by = request.user
            dispute.closed_at = timezone.now()
        elif decision == "dismiss":
            if not note:
                messages.error(request, "A dismissal reason is required.")
                return redirect("accounts:moderation")
            dispute.status = DisputeCase.Status.DISMISSED
            dispute.resolution_notes = note
            dispute.closed_by = request.user
            dispute.closed_at = timezone.now()
        else:
            messages.error(request, "Unknown dispute action.")
            return redirect("accounts:moderation")

        dispute.save()
        record_audit(
            action=ModerationAudit.Action.DISPUTE_UPDATED,
            actor=request.user,
            dog=dispute.dog,
            kennel=dispute.dog.kennel,
            dispute=dispute,
            summary={"decision": decision, "status": dispute.status},
            note=note,
        )
        Notification.objects.create(
            user=dispute.opened_by,
            title=f"Review case {dispute.get_status_display().lower()}",
            message=f"Your review case for {dispute.dog.name} is now {dispute.get_status_display().lower()}.",
            link="/member/disputes/",
        )

    messages.success(request, "Dispute case updated.")
    return redirect("accounts:moderation")


@login_required
def verification_dashboard(request):
    if not can_manage_verification(request.user):
        raise PermissionDenied

    pending = Submission.objects.filter(status=Submission.Status.PENDING)
    pending_count = pending.count()
    yellow_count = pending.filter(risk_level=SubmissionRiskLevel.YELLOW).count()
    red_count = pending.filter(risk_level=SubmissionRiskLevel.RED).count()
    second_count = pending.filter(
        verification_status=SubmissionVerificationStatus.AWAITING_SECOND
    ).count()
    overrides_count = SubmissionReview.objects.filter(
        action__in=[
            SubmissionReview.Action.OVERRIDE_APPROVED,
            SubmissionReview.Action.OVERRIDE_REQUESTED,
        ]
    ).count()

    reviewer_rows = []
    staff_users = list(
        get_user_model().objects.filter(is_staff=True).order_by("username")
    )
    decision_actions = {
        SubmissionReview.Action.APPROVED,
        SubmissionReview.Action.REJECTED,
        SubmissionReview.Action.OVERRIDE_APPROVED,
        SubmissionReview.Action.OVERRIDE_REQUESTED,
        SubmissionReview.Action.SECOND_APPROVED,
        SubmissionReview.Action.SECOND_REJECTED,
    }
    for user in staff_users:
        decisions = list(
            SubmissionReview.objects.filter(reviewer=user)
            .select_related("submission")
            .order_by("created_at")
        )
        decision_rows = [row for row in decisions if row.action in decision_actions]
        approved = sum(
            row.action
            in {
                SubmissionReview.Action.APPROVED,
                SubmissionReview.Action.OVERRIDE_APPROVED,
                SubmissionReview.Action.SECOND_APPROVED,
            }
            for row in decision_rows
        )
        rejected = sum(
            row.action
            in {
                SubmissionReview.Action.REJECTED,
                SubmissionReview.Action.SECOND_REJECTED,
            }
            for row in decision_rows
        )
        overrides = sum(
            row.action
            in {
                SubmissionReview.Action.OVERRIDE_APPROVED,
                SubmissionReview.Action.OVERRIDE_REQUESTED,
            }
            for row in decision_rows
        )
        flagged = sum(bool(row.warnings_snapshot) for row in decision_rows)
        high_risk_approved = sum(
            row.action == SubmissionReview.Action.SECOND_APPROVED
            for row in decision_rows
        )
        durations = [
            row.created_at - row.submission.created_at
            for row in decision_rows
            if row.created_at and row.submission.created_at
        ]
        avg_seconds = (
            sum(item.total_seconds() for item in durations) / len(durations)
            if durations
            else 0
        )
        reviewer_rows.append(
            {
                "user": user,
                "admin_label": admin_public_label(user),
                "role": moderation_role(user),
                "reviews": len(decision_rows),
                "approved": approved,
                "rejected": rejected,
                "flagged": flagged,
                "overrides": overrides,
                "override_rate": (
                    round((overrides / len(decision_rows)) * 100, 1)
                    if decision_rows
                    else 0
                ),
                "high_risk_approved": high_risk_approved,
                "average_review_hours": round(avg_seconds / 3600, 1) if avg_seconds else 0,
                "unusual_override": False,
            }
        )

    established = [row for row in reviewer_rows if row["reviews"] >= 20]
    established_rates = [row["override_rate"] for row in established]
    peer_average = (
        sum(established_rates) / len(established_rates)
        if established_rates
        else 0
    )
    warning_threshold = max(10.0, peer_average + 5.0)
    for row in reviewer_rows:
        peers = [
            other["override_rate"]
            for other in established
            if other["user"].pk != row["user"].pk
        ]
        if row["reviews"] >= 20 and peers:
            row_peer_average = sum(peers) / len(peers)
            row["unusual_override"] = (
                row["override_rate"] > max(10.0, row_peer_average + 5.0)
            )
        else:
            row["unusual_override"] = False

    flagged_queue = list(
        pending.exclude(risk_level=SubmissionRiskLevel.GREEN)
        .select_related("submitted_by", "kennel", "dog", "litter")
        .order_by("-requires_second_review", "created_at")[:50]
    )
    high_risk_queue = [
        item for item in flagged_queue
        if item.risk_level == SubmissionRiskLevel.RED
    ][:30]
    second_queue = list(
        pending.filter(
            verification_status=SubmissionVerificationStatus.AWAITING_SECOND
        )
        .select_related("submitted_by", "kennel", "dog", "litter")
        .order_by("created_at")[:50]
    )
    recent_overrides = list(
        SubmissionReview.objects.filter(
            action__in=[
                SubmissionReview.Action.OVERRIDE_APPROVED,
                SubmissionReview.Action.OVERRIDE_REQUESTED,
                SubmissionReview.Action.SECOND_APPROVED,
                SubmissionReview.Action.SECOND_REJECTED,
            ]
        )
        .select_related("submission", "reviewer", "submission__kennel", "submission__dog", "submission__litter")
        .order_by("-created_at")[:50]
    )
    recent_changes = list(
        ModerationAudit.objects.filter(
            action__in=[
                ModerationAudit.Action.RECORD_CHANGED,
                ModerationAudit.Action.RECORD_LOCK_CHANGED,
            ]
        )
        .select_related("actor", "dog", "litter", "submission")
        .order_by("-created_at")[:30]
    )
    locked_dogs = list(
        Dog.objects.filter(is_record_locked=True)
        .select_related("record_locked_by", "kennel")
        .order_by("-record_locked_at", "name")[:30]
    )
    locked_litters = list(
        Litter.objects.filter(is_record_locked=True)
        .select_related("record_locked_by", "kennel")
        .order_by("-record_locked_at", "code")[:30]
    )
    rules = list(VerificationRule.objects.order_by("code"))
    role_assignments = {
        item.user_id: item
        for item in ModerationRoleAssignment.objects.select_related("user").all()
    }
    for user in staff_users:
        user.moderation_assignment = role_assignments.get(user.pk)

    return render(
        request,
        "accounts/verification_dashboard.html",
        {
            "pending_count": pending_count,
            "yellow_count": yellow_count,
            "red_count": red_count,
            "second_count": second_count,
            "overrides_count": overrides_count,
            "reviewer_rows": reviewer_rows,
            "peer_override_average": round(peer_average, 1),
            "override_warning_threshold": round(warning_threshold, 1),
            "flagged_queue": flagged_queue,
            "high_risk_queue": high_risk_queue,
            "second_queue": second_queue,
            "recent_overrides": recent_overrides,
            "recent_changes": recent_changes,
            "locked_dogs": locked_dogs,
            "locked_litters": locked_litters,
            "rules": rules,
            "staff_users": staff_users,
            "role_choices": ModerationRoleAssignment.Role.choices,
            "risk_choices": SubmissionRiskLevel.choices,
        },
    )


@login_required
@require_POST
def moderation_set_role(request):
    if not can_manage_verification(request.user):
        raise PermissionDenied

    user_id = request.POST.get("user_id", "").strip()
    user_lookup = request.POST.get("user_lookup", "").strip()
    if user_id:
        if not user_id.isdigit():
            messages.error(request, "Invalid administrator account ID.")
            return redirect("accounts:verification-dashboard")
        target = get_object_or_404(get_user_model(), pk=int(user_id))
    elif user_lookup:
        target = get_user_model().objects.filter(
            Q(username__iexact=user_lookup) | Q(email__iexact=user_lookup)
        ).first()
        if target is None:
            messages.error(request, "No user matches that username or email.")
            return redirect("accounts:verification-dashboard")
    else:
        messages.error(request, "Choose a user or enter a username/email.")
        return redirect("accounts:verification-dashboard")
    requested_role = request.POST.get("role", "").strip()
    if target.is_superuser:
        messages.info(request, "Superusers always have owner-level verification authority.")
        return redirect("accounts:verification-dashboard")

    current = ModerationRoleAssignment.objects.filter(user=target).first()
    before = current.role if current else ""
    if not requested_role:
        requested_role = ModerationRoleAssignment.Role.NONE
    if requested_role not in dict(ModerationRoleAssignment.Role.choices):
        messages.error(request, "Unknown moderation role.")
        return redirect("accounts:verification-dashboard")
    assignment, _ = ModerationRoleAssignment.objects.update_or_create(
        user=target,
        defaults={
            "role": requested_role,
            "assigned_by": request.user,
        },
    )
    should_be_staff = requested_role != ModerationRoleAssignment.Role.NONE
    if target.is_staff != should_be_staff:
        target.is_staff = should_be_staff
        target.save(update_fields=("is_staff",))

    record_audit(
        action=ModerationAudit.Action.VERIFICATION,
        actor=request.user,
        summary={
            "type": "moderation_role_changed",
            "target_admin_number": assignment.admin_number,
            "previous_role": before,
            "new_role": requested_role,
        },
        note="Owner updated moderation authority.",
    )
    messages.success(request, "Moderator authority updated.")
    return redirect("accounts:verification-dashboard")


@login_required
@require_POST
def moderation_record_lock(request):
    if not can_manage_verification(request.user):
        raise PermissionDenied

    record_type = request.POST.get("record_type", "").strip()
    record_id = request.POST.get("record_id", "").strip()
    action = request.POST.get("action", "").strip()
    reason = request.POST.get("reason", "").strip()
    if action not in {"lock", "unlock"} or record_type not in {"dog", "litter"}:
        messages.error(request, "Invalid record-lock request.")
        return redirect("accounts:verification-dashboard")
    if not reason:
        messages.error(request, "A reason is required to change a record lock.")
        return redirect("accounts:verification-dashboard")

    try:
        parsed_record_id = uuid.UUID(record_id)
    except (TypeError, ValueError):
        messages.error(request, "Enter a valid dog or litter UUID.")
        return redirect("accounts:verification-dashboard")

    model = Dog if record_type == "dog" else Litter
    record = get_object_or_404(model, pk=parsed_record_id)
    before = bool(record.is_record_locked)
    desired = action == "lock"
    if before == desired:
        messages.info(
            request,
            f"This {record_type} record is already {'locked' if desired else 'unlocked'}.",
        )
        return redirect("accounts:verification-dashboard")

    record.is_record_locked = desired
    record.record_locked_at = timezone.now() if desired else None
    record.record_locked_by = request.user if desired else None
    record.save(
        update_fields=(
            "is_record_locked",
            "record_locked_at",
            "record_locked_by",
        )
    )
    record_audit(
        action=ModerationAudit.Action.RECORD_LOCK_CHANGED,
        actor=request.user,
        dog=record if record_type == "dog" else None,
        kennel=record.kennel,
        litter=record if record_type == "litter" else None,
        summary={
            "record_type": record_type,
            "record_id": str(record.pk),
            "previous_locked": before,
            "new_locked": desired,
        },
        note=reason,
    )
    messages.success(
        request,
        f"{record_type.title()} record {'locked' if desired else 'unlocked'} with an audit entry.",
    )
    return redirect("accounts:verification-dashboard")


@login_required
@require_POST
def verification_rule_update(request, pk):
    if not can_manage_verification(request.user):
        raise PermissionDenied

    rule = get_object_or_404(VerificationRule, pk=pk)
    risk_level = request.POST.get("risk_level", "").strip()
    if risk_level not in dict(SubmissionRiskLevel.choices):
        messages.error(request, "Unknown verification risk level.")
        return redirect("accounts:verification-dashboard")

    before = {
        "enabled": rule.enabled,
        "risk_level": rule.risk_level,
        "second_approval_required": rule.second_approval_required,
    }
    rule.enabled = request.POST.get("enabled") == "on"
    rule.risk_level = risk_level
    rule.second_approval_required = request.POST.get("second_approval_required") == "on"
    rule.updated_by = request.user
    rule.save()
    invalidated_count = Submission.objects.filter(
        status=Submission.Status.PENDING
    ).update(
        verification_status=SubmissionVerificationStatus.UNCHECKED,
        verification_checked_at=None,
    )
    record_audit(
        action=ModerationAudit.Action.VERIFICATION,
        actor=request.user,
        summary={
            "type": "verification_rule_changed",
            "rule": rule.code,
            "previous": before,
            "new": {
                "enabled": rule.enabled,
                "risk_level": rule.risk_level,
                "second_approval_required": rule.second_approval_required,
            },
        },
        note="Owner updated an automated verification rule.",
    )
    messages.success(
        request,
        f"Verification rule '{rule.title}' updated. {invalidated_count} pending submission(s) will be rechecked when opened or reviewed.",
    )
    return redirect("accounts:verification-dashboard")


@login_required
def data_health(request):
    if not can_review_submissions(request.user):
        raise PermissionDenied

    cache_key = "admin:data-health:quick:v2"
    report = None if request.GET.get("refresh") == "1" else cache.get(cache_key)
    if report is None:
        report = quick_quality_report(sample_limit=12)
        cache.set(cache_key, report, timeout=60)

    counts = report["counts"]
    critical_total = sum(
        counts.get(key, 0)
        for key in (
            "sire_sex_conflicts",
            "dam_sex_conflicts",
            "same_parent_conflicts",
            "parent_date_conflicts",
        )
    )
    return render(
        request,
        "accounts/data_health.html",
        {
            "report": report,
            "counts": counts,
            "critical_total": critical_total,
        },
    )


@login_required
def moderation_audit(request):
    if not can_review_submissions(request.user):
        raise PermissionDenied
    events = ModerationAudit.objects.select_related(
        "actor", "dog", "kennel", "litter", "submission", "dispute"
    )

    query = request.GET.get("q", "").strip()
    action = request.GET.get("action", "").strip()
    actor = request.GET.get("actor", "").strip()

    if query:
        query_filter = (
            Q(dog__name__icontains=query)
            | Q(kennel__name__icontains=query)
            | Q(litter__code__icontains=query)
            | Q(note__icontains=query)
        )
        query_digits = "".join(ch for ch in query if ch.isdigit())
        if query_digits:
            query_filter |= Q(
                actor_admin_number_snapshot=int(query_digits)
            ) | Q(
                actor__ancestry_moderation_role__admin_number=int(query_digits)
            )
        events = events.filter(query_filter).distinct()
    if action in dict(ModerationAudit.Action.choices):
        events = events.filter(action=action)
    if actor:
        actor_digits = "".join(ch for ch in actor if ch.isdigit())
        if actor_digits:
            events = events.filter(
                Q(actor_admin_number_snapshot=int(actor_digits))
                | Q(actor__ancestry_moderation_role__admin_number=int(actor_digits))
            ).distinct()
        else:
            events = events.none()

    events = events.order_by("-created_at")
    paginator = Paginator(events, 100)
    page_obj = paginator.get_page(request.GET.get("page"))
    query_params = request.GET.copy()
    query_params.pop("page", None)
    return render(
        request,
        "accounts/moderation_audit.html",
        {
            "events": page_obj.object_list,
            "page_obj": page_obj,
            "querystring": query_params.urlencode(),
            "actions": ModerationAudit.Action.choices,
            "filters": {"q": query, "action": action, "actor": actor},
        },
    )
