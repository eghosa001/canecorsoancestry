"""Read-only Google Search Console data for super administrators.

The credential belongs to a service account granted Search Console access.
Never put it in the repository or return API details to the admin browser.
"""
import base64
import binascii
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from django.core.cache import cache
from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account

logger = logging.getLogger(__name__)

SCOPES = ("https://www.googleapis.com/auth/webmasters.readonly",)
ALLOWED_DAYS = (1, 7, 28, 90)
CACHE_SECONDS = 600
DEFAULT_PROPERTY = "sc-domain:canecorsoancestry.com"


def _query(session, property_url, start_date, end_date, dimensions=(), row_limit=10):
    url = (
        "https://www.googleapis.com/webmasters/v3/sites/"
        + quote(property_url, safe="")
        + "/searchAnalytics/query"
    )
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "type": "web",
        "rowLimit": row_limit,
    }
    if dimensions:
        body["dimensions"] = list(dimensions)
    response = session.post(url, json=body, timeout=(3, 10))
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("Unexpected Search Console response")
    return data.get("rows") or []


def _metric_row(row):
    return {
        "clicks": int(row.get("clicks") or 0),
        "impressions": int(row.get("impressions") or 0),
        "ctr": round(100 * float(row.get("ctr") or 0), 2),
        "position": round(float(row.get("position") or 0), 2),
    }


def get_search_console_report(days=28):
    """Server-only data, cached briefly to avoid excessive API requests."""
    if days not in ALLOWED_DAYS:
        days = 28
    raw = os.getenv("CCA_GSC_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        encoded = os.getenv("CCA_GSC_SERVICE_ACCOUNT_B64", "").strip()
        if encoded:
            try:
                raw = base64.b64decode(encoded, validate=True).decode("utf-8")
            except (binascii.Error, UnicodeDecodeError):
                logger.warning("Search Console credential encoding is invalid")
                return {"status": "error", "days": days}
    site_url = os.getenv("CCA_GSC_SITE_URL", DEFAULT_PROPERTY).strip() or DEFAULT_PROPERTY
    if not raw:
        return {"status": "unconfigured", "days": days}

    # Include a digest of the credential in the cache key, so rotation cannot
    # accidentally keep showing old data for a different Google principal.
    import hashlib
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    cache_key = f"cca:gsc:v1:{site_url}:{days}:{digest}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    # Search Console data typically settles 2-3 days after each search day.
    # Reporting an older settled day is more honest than a misleading "today".
    end = datetime.now(timezone.utc).date() - timedelta(days=3)
    start = end - timedelta(days=days - 1)
    start_date, end_date = start.isoformat(), end.isoformat()
    try:
        info = json.loads(raw)
        if not isinstance(info, dict) or info.get("type") != "service_account":
            raise ValueError("Expected Google service-account JSON")
        credentials = service_account.Credentials.from_service_account_info(
            info, scopes=SCOPES
        )
        with AuthorizedSession(credentials) as session:
            total = _query(session, site_url, start_date, end_date, row_limit=1)
            daily = _query(
                session, site_url, start_date, end_date,
                dimensions=("date",), row_limit=max(100, days)
            )
            pages = _query(
                session, site_url, start_date, end_date,
                dimensions=("page",), row_limit=10
            )
            queries = _query(
                session, site_url, start_date, end_date,
                dimensions=("query",), row_limit=10
            )
        summary = _metric_row(total[0]) if total else {
            "clicks": 0, "impressions": 0, "ctr": 0, "position": 0
        }
        daily_by_date = {
            row["keys"][0]: _metric_row(row)
            for row in daily if row.get("keys")
        }
        history = []
        for offset in range(days):
            date = (start + timedelta(days=offset)).isoformat()
            history.append({"date": date, **daily_by_date.get(date, {
                "clicks": 0, "impressions": 0, "ctr": 0, "position": 0
            })})
        max_impressions = max((row["impressions"] for row in history), default=0)
        for row in history:
            row["width"] = round(100 * row["impressions"] / max_impressions) if max_impressions else 0

        def top_rows(rows):
            return [
                {"key": row["keys"][0], **_metric_row(row)}
                for row in rows if row.get("keys")
            ]

        report = {
            "status": "ready",
            "days": days,
            "start_date": start_date,
            "end_date": end_date,
            "site_url": site_url,
            **summary,
            "daily": history,
            "pages": top_rows(pages),
            "queries": top_rows(queries),
        }
    except (Exception):
        # Credentials, tokens, GSC API errors and underlying exceptions are
        # intentionally not sent to templates or users.
        logger.warning("Search Console admin report is unavailable")
        report = {"status": "error", "days": days}

    cache.set(cache_key, report, CACHE_SECONDS if report["status"] == "ready" else 60)
    return report
