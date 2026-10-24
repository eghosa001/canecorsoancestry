"""Higher only-for-isolated-CI login allowance for repeated synthetic accounts.

Production uses core.middleware.AbuseProtectionMiddleware unchanged.
Rate-limit behavior remains tested in the ordinary Django backend suite.
"""
from core.middleware import AbuseProtectionMiddleware


class IsolatedQAAbuseProtectionMiddleware(AbuseProtectionMiddleware):
    RULES = tuple(
        (prefix, 200 if prefix in ("/accounts/login/", "/admin/login/") else limit, window)
        for prefix, limit, window in AbuseProtectionMiddleware.RULES
    )
