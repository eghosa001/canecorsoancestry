"""Read-only live edge contract for Paystack anti-forgery and billing transparency."""
import json
import os
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

BASE = os.environ.get(
    "PRODUCTION_BASE_URL",
    "https://canecorsoancestry-site-edge.aighewieghosa111.workers.dev",
).rstrip("/")
parsed = urlsplit(BASE)
if parsed.scheme != "https" or not parsed.hostname or parsed.path or parsed.query:
    raise SystemExit("Refusing to probe an invalid public HTTPS origin")

def fetch(path, *, method="GET", body=None, headers=None):
    request = Request(
        BASE + path,
        data=body,
        headers={"User-Agent": "cca-payment-readiness-probe/1.0", **(headers or {})},
        method=method,
    )
    try:
        with urlopen(request, timeout=25) as response:
            return response.status, response.read(300_000).decode("utf-8", errors="replace")
    except HTTPError as exc:
        return exc.code, exc.read(12_000).decode("utf-8", errors="replace")

def expect(path, expected, *, method="GET", body=None, headers=None, contains=()):
    status, html = fetch(path, method=method, body=body, headers=headers)
    if status != expected or any(token not in html for token in contains):
        raise AssertionError(
            f"{method} {path}: HTTP {status}, expected {expected}, content check {contains!r}"
        )
    print(f"PASS: {method} {path} HTTP {status}")

expect("/member/payments/paystack/callback/", 400)  # No reference: no Paystack call.
webhook = "/member/payments/paystack/webhook/"
expect(webhook, 405)  # Payment notification must be POST-only.
expect(
    webhook, 400, method="POST",
    body=json.dumps({"event": "charge.success", "data": {"reference": "invalid-read-only-probe"}}).encode(),
    headers={
        "Content-Type": "application/json",
        "x-paystack-signature": "invalid-signature",
    },
)  # Invalid HMAC is rejected before any payment lookup or update.
expect("/billing-policy/", 200, contains=("₦500", "₦1,500", "review"))
expect("/privacy/", 200, contains=("Privacy notice",))
expect("/terms/", 200, contains=("Terms of use",))
print("PASS: public billing/webhook anti-forgery and policy routes are accessible; no charges, emails or writes made.")
