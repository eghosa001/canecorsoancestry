"""Cloudflare HTTP analytics for the private super-admin dashboard."""
import logging
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.core.cache import cache

log = logging.getLogger(__name__)
API = "https://api.cloudflare.com/client/v4/graphql"
# Public Web Analytics identifiers, not API credentials. This site already
# collects browser beacons; do not install a second tracker.
WEB_ACCOUNT = "19a03bec57c0277e01e1e70e241576af"
WEB_SITE = "68b036386f3841018058c0128192ef26"
WEB_DASHBOARD = (
    f"https://dash.cloudflare.com/{WEB_ACCOUNT}/web-analytics/overview/visits"
    f"?siteTag~in={WEB_SITE}&excludeBots=Yes"
)
BROWSER_QUERY = """
query BrowserTraffic($account: string,
  $audienceFilter: AccountRumPageloadEventsAdaptiveGroupsFilter_InputObject,
  $automatedFilter: AccountRumPageloadEventsAdaptiveGroupsFilter_InputObject) {
 viewer {
  accounts(filter: {accountTag: $account}) {
   audience: rumPageloadEventsAdaptiveGroups(limit: 1, filter: $audienceFilter) {
    count sum {visits}
   }
   automated: rumPageloadEventsAdaptiveGroups(limit: 1, filter: $automatedFilter) {
    count sum {visits}
   }
  }
 }
}
"""
QUERY = """
query Traffic($zone: string, $since: Date, $until: Date,
              $start: Time, $end: Time, $host: string) {
 viewer {
  zones(filter: {zoneTag: $zone}) {
   daily: httpRequests1dGroups(
    limit: 31, orderBy: [date_ASC],
    filter: {date_geq: $since, date_leq: $until}
   ) {dimensions {date} sum {requests pageViews} uniq {uniques}}
   paths: httpRequestsAdaptiveGroups(
    limit: 100, orderBy: [count_DESC],
    filter: {datetime_geq: $start, datetime_lt: $end,
             requestSource: "eyeball", clientRequestHTTPHost: $host}
   ) {count dimensions {clientRequestPath}}
   countries: httpRequestsAdaptiveGroups(
    limit: 12, orderBy: [count_DESC],
    filter: {datetime_geq: $start, datetime_lt: $end,
             requestSource: "eyeball", clientRequestHTTPHost: $host}
   ) {count dimensions {clientCountryName}}
  }
 }
}
"""


def _count(value):
    try:
        return max(0, int(value or 0))
    except (ValueError, TypeError):
        return 0


def _public_path(path):
    return (isinstance(path, str) and len(path) <= 255 and (
        path == "/" or path.startswith((
            "/dogs/", "/kennels/", "/pedigrees/", "/litters/", "/statistics/"
        ))
    ))


def get_browser_traffic(token, days, now):
    """Browser observations with known bots excluded; never claim exact humans.

    Raw HTTP counts cannot be subtracted from beacon page loads to calculate
    crawlers. They measure different populations and have different coverage.
    """
    host = urlparse(settings.SITE_URL).hostname or "canecorsoancestry.com"
    first = now.date() - timedelta(days=days - 1)
    filters = {
        "siteTag": WEB_SITE,
        "requestHost": host,
        "requestPath_notlike": "/admin/%",
        "datetime_geq": first.isoformat() + "T00:00:00Z",
        "datetime_lt": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    unavailable = {"status": "unavailable", "dashboard_url": WEB_DASHBOARD}
    try:
        response = requests.post(
            API, json={"query": BROWSER_QUERY, "variables": {
                "account": WEB_ACCOUNT,
                "audienceFilter": {**filters, "bot": 0},
                "automatedFilter": {**filters, "bot": 1},
            }}, headers={"Authorization": f"Bearer {token}"}, timeout=(3, 7),
        )
        response.raise_for_status()
        result = response.json()
        if result.get("errors"):
            raise ValueError("Browser analytics unavailable")
        account = result["data"]["viewer"]["accounts"][0]
        audience = account["audience"]
        automated = account["automated"]
        if not isinstance(audience, list) or not isinstance(automated, list):
            raise ValueError("Missing browser analytics")
        return {
            "status": "ready", "dashboard_url": WEB_DASHBOARD,
            "page_views": sum(_count(row.get("count")) for row in audience),
            "visits": sum(_count((row.get("sum") or {}).get("visits")) for row in audience),
            "automated_page_views": sum(_count(row.get("count")) for row in automated),
        }
    except (requests.RequestException, ValueError, TypeError, KeyError, IndexError) as exc:
        log.warning("Browser analytics request unavailable (%s)", type(exc).__name__)
        return unavailable


def get_traffic(days=7):
    if days not in (1, 7, 30):
        days = 7
    zone = os.getenv("CCA_TRAFFIC_ZONE_ID") or os.getenv("CLOUDFLARE_ZONE_ID")
    token = os.getenv("CCA_TRAFFIC_API_TOKEN") or os.getenv("CLOUDFLARE_ANALYTICS_API_TOKEN")
    if not zone or not token:
        return {"status": "unconfigured", "days": days}
    now = datetime.now(timezone.utc)
    first = now.date() - timedelta(days=days - 1)
    host = urlparse(settings.SITE_URL).hostname or "canecorsoancestry.com"
    key = f"cca:traffic:v2:{zone}:{host}:{days}:{now.date()}"
    stored = cache.get(key)
    if stored is not None:
        return stored

    variables = {
        "zone": zone,
        "since": first.isoformat(),
        "until": now.date().isoformat(),
        "start": first.isoformat() + "T00:00:00Z",
        "end": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "host": host,
    }
    try:
        response = requests.post(
            API, json={"query": QUERY, "variables": variables},
            headers={"Authorization": f"Bearer {token}"},
            timeout=(3, 7),
        )
        response.raise_for_status()
        result = response.json()
        if result.get("errors"):
            raise ValueError("GraphQL error")
        zone_data = result["data"]["viewer"]["zones"][0]
    except (requests.RequestException, ValueError, TypeError, KeyError, IndexError) as exc:
        log.warning("Cloudflare analytics request unavailable (%s)", type(exc).__name__)
        return {"status": "error", "days": days}

    daily = {}
    for item in zone_data.get("daily") or []:
        date = (item.get("dimensions") or {}).get("date")
        if date:
            totals = item.get("sum") or {}
            uniques = item.get("uniq") or {}
            daily[date] = {
                "views": _count(totals.get("pageViews")),
                "requests": _count(totals.get("requests")),
                "uniques": _count(uniques.get("uniques")),
            }
    rows = []
    for i in range(days):
        date = (first + timedelta(days=i)).isoformat()
        rows.append({"date": date, **daily.get(date, {
            "views": 0, "requests": 0, "uniques": 0
        })})
    max_views = max((row["views"] for row in rows), default=0)
    for row in rows:
        row["width"] = round(row["views"] * 100 / max_views) if max_views else 0

    paths = []
    for item in zone_data.get("paths") or []:
        path = (item.get("dimensions") or {}).get("clientRequestPath")
        if _public_path(path):
            paths.append({"path": path, "requests": _count(item.get("count"))})
        if len(paths) == 15:
            break
    countries = []
    for item in zone_data.get("countries") or []:
        name = (item.get("dimensions") or {}).get("clientCountryName")
        if name:
            countries.append({"name": name, "requests": _count(item.get("count"))})

    report = {
        "status": "ready", "days": days, "daily": rows,
        "page_views": sum(row["views"] for row in rows),
        "requests": sum(row["requests"] for row in rows),
        "unique_today": rows[-1]["uniques"],
        "average_daily_uniques": round(sum(row["uniques"] for row in rows) / days, 1),
        "paths": paths, "countries": countries,
        "browser": get_browser_traffic(token, days, now),
        "refreshed": now.strftime("%d %b %Y %H:%M UTC"),
    }
    cache.set(key, report, timeout=300)
    return report

