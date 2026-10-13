#!/usr/bin/env bash
# Read-only integration configuration gate. No payment or email delivery is attempted.
set -euo pipefail
[[ "${GITHUB_REPOSITORY:-}" == "eghosa001/canecorsoancestry" &&
    "${GITHUB_REF:-}" == "refs/heads/main" &&
    "$(uname -m)" == "aarch64" &&
    "$(id -un)" == "opc" ]] || exit 2
test "$(sudo -n cat /etc/cca/oracle-db-mode)" = local
sudo -n systemctl is-active --quiet cca-oracle-staging.service
sudo -n systemctl is-active --quiet cca-pg-shadow.service
sudo -n podman exec cca-oracle-staging python manage.py check --deploy
sudo -n podman exec cca-oracle-staging python manage.py shell -c '
from django.conf import settings
from django.db import connection
checks = {
    "https": settings.SITE_URL.startswith("https://"),
    "email_enabled": settings.ACCOUNT_EMAIL_ENABLED,
    "verification_enabled": settings.REQUIRE_EMAIL_VERIFICATION,
    "smtp_configured": bool(settings.EMAIL_HOST and settings.EMAIL_HOST_USER and settings.EMAIL_HOST_PASSWORD),
    "paystack_configured": bool(settings.PAYSTACK_SECRET_KEY),
    "support_contact": bool(settings.SUPPORT_EMAIL),
    "debug_off": not settings.DEBUG,
}
with connection.cursor() as cursor:
    cursor.execute("SELECT 1")
    checks["database_connected"] = cursor.fetchone()[0] == 1
for label, good in checks.items():
    print("{}: {}".format(label, "PASS" if good else "BLOCK"))
assert all(checks.values()), "Commercial-launch configuration is incomplete."
'
