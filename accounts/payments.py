import hashlib
import hmac
import json

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import SubmissionPayment


class PaystackError(RuntimeError):
    pass


def _headers():
    secret = getattr(settings, "PAYSTACK_SECRET_KEY", "")
    if not secret:
        raise PaystackError("Paystack is not configured yet.")
    return {
        "Authorization": f"Bearer {secret}",
        "Content-Type": "application/json",
    }


def initialize_transaction(payment, callback_url):
    payload = {
        "email": payment.user.email,
        "amount": str(payment.amount_kobo),
        "currency": payment.currency,
        "reference": payment.reference,
        "callback_url": callback_url,
        "metadata": json.dumps(
            {
                "payment_id": str(payment.pk),
                "package": payment.package,
                "kennel_id": str(payment.kennel_id),
                "user_id": str(payment.user_id),
            }
        ),
    }
    try:
        response = requests.post(
            f"{settings.PAYSTACK_BASE_URL}/transaction/initialize",
            headers=_headers(),
            json=payload,
            timeout=settings.PAYSTACK_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise PaystackError("Unable to start the Paystack payment.") from exc

    data = body.get("data") or {}
    if not body.get("status") or not data.get("authorization_url") or not data.get("access_code"):
        raise PaystackError(body.get("message") or "Paystack did not return a checkout URL.")
    return data


def verify_transaction(reference):
    try:
        response = requests.get(
            f"{settings.PAYSTACK_BASE_URL}/transaction/verify/{reference}",
            headers=_headers(),
            timeout=settings.PAYSTACK_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise PaystackError("Unable to verify the Paystack payment.") from exc

    if not body.get("status") or not isinstance(body.get("data"), dict):
        raise PaystackError(body.get("message") or "Paystack could not verify this payment.")
    return body["data"]


def _metadata_dict(data):
    metadata = data.get("metadata") or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except ValueError:
            metadata = {}
    return metadata if isinstance(metadata, dict) else {}


@transaction.atomic
def record_successful_payment(reference, data):
    payment = (
        SubmissionPayment.objects.select_for_update()
        .select_related("user", "kennel")
        .get(reference=reference)
    )
    if payment.status == SubmissionPayment.Status.PAID:
        return payment

    if data.get("reference") != payment.reference:
        raise PaystackError("Payment reference mismatch.")
    if data.get("status") != "success":
        raise PaystackError("Payment has not completed successfully.")
    # Provider payloads are untrusted even after a successful verify request.
    # Never let malformed amounts or mixed merchant metadata cause a 500 or
    # accidentally attach a transaction to the wrong kennel/member package.
    amount = data.get("amount")
    if isinstance(amount, bool) or not isinstance(amount, (int, str)):
        raise PaystackError("Invalid payment amount.")
    try:
        parsed_amount = int(amount)
    except (ValueError, TypeError, OverflowError) as exc:
        raise PaystackError("Invalid payment amount.") from exc
    if isinstance(amount, str) and (not amount.isascii() or not amount.isdecimal()):
        raise PaystackError("Invalid payment amount.")
    if parsed_amount != payment.amount_kobo:
        raise PaystackError("Payment amount mismatch.")
    if str(data.get("currency") or "").upper() != payment.currency:
        raise PaystackError("Payment currency mismatch.")

    metadata = _metadata_dict(data)
    expected_metadata = {
        "payment_id": payment.pk,
        "user_id": payment.user_id,
        "kennel_id": payment.kennel_id,
        "package": payment.package,
    }
    for key, expected in expected_metadata.items():
        if key in metadata and str(metadata[key]) != str(expected):
            raise PaystackError("Payment metadata mismatch.")

    payment.status = SubmissionPayment.Status.PAID
    payment.paystack_transaction_id = str(data.get("id") or "")
    payment.paid_at = timezone.now()
    payment.raw_response = data
    payment.save(
        update_fields=(
            "status",
            "paystack_transaction_id",
            "paid_at",
            "raw_response",
            "updated_at",
        )
    )
    return payment


def webhook_signature_valid(raw_body, signature):
    secret = getattr(settings, "PAYSTACK_SECRET_KEY", "")
    if not secret or not signature:
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha512,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
