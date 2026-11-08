"""Read-only live Paystack authentication check (no charges and no transfers).

Uses the documented GET /balance endpoint but never prints account balances,
identities, raw HTTP responses or secret keys. It only reports whether the
configured production key authenticates to Paystack over HTTPS.
"""
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class PaymentTransportError(RuntimeError):
    pass


class NoRedirects(HTTPRedirectHandler):
    # urllib otherwise may propagate the Bearer token across redirects.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def check_paystack_transport(*, secret_key, base_url, opener=None):
    if not isinstance(secret_key, str) or not secret_key:
        raise PaymentTransportError("Production Paystack secret is not configured.")
    if not secret_key.startswith("sk_live_"):
        raise PaymentTransportError(
            "Production Paystack uses no live secret key; check payment mode."
        )
    parsed = urlsplit(base_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "api.paystack.co"
        or parsed.username
        or parsed.password
        or parsed.port
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise PaymentTransportError("Paystack API endpoint must be the official HTTPS host.")
    request = Request(
        "https://api.paystack.co/balance",
        method="GET",
        headers={
            "Authorization": f"Bearer {secret_key}",
            "Accept": "application/json",
            "User-Agent": "CCA-Paystack-Transport-Probe/1.0",
        },
    )
    try:
        open_request = opener if opener is not None else build_opener(NoRedirects()).open
        with open_request(request, timeout=12) as response:
            if response.status != 200:
                raise PaymentTransportError("Paystack read-only authentication check failed.")
            payload = json.load(response)
            if not isinstance(payload, dict) or payload.get("status") is not True:
                raise PaymentTransportError("Paystack did not confirm authorized access.")
            if not isinstance(payload.get("data"), list):
                raise PaymentTransportError("Paystack returned an unexpected balance API response.")
    except PaymentTransportError:
        raise
    except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        # Never propagate raw Paystack errors, account balances, or any key.
        raise PaymentTransportError("Unable to verify Paystack live API authentication.") from None


def main():
    import django
    django.setup()
    from django.conf import settings

    try:
        check_paystack_transport(
            secret_key=settings.PAYSTACK_SECRET_KEY,
            base_url=settings.PAYSTACK_BASE_URL,
        )
    except PaymentTransportError as exc:
        print(f"::error::{exc}")
        raise SystemExit(1) from None
    print("PASS: Live Paystack HTTPS API authorization verified with GET only; no charge, transfer or balance disclosed.")


if __name__ == "__main__":
    main()
