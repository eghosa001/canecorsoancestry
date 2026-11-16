"""Keep browser audience estimates separate from raw edge traffic."""
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.template import Context, Engine
from django.test import SimpleTestCase, override_settings

from core.traffic import get_browser_traffic


@override_settings(SITE_URL="https://canecorsoancestry.com")
class BrowserTrafficTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def response(self, account):
        response = Mock()
        response.json.return_value = {"data": {"viewer": {"accounts": [account]}}}
        return response

    def test_browser_metrics_use_explicit_bot_filter_and_public_site(self):
        response = self.response({
            "audience": [{"count": 90, "sum": {"visits": 62}}],
            "automated": [{"count": 7, "sum": {"visits": 4}}],
        })
        with patch("core.traffic.requests.post", return_value=response) as post:
            report = get_browser_traffic("test-token", 1, datetime.now(timezone.utc))
        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["page_views"], 90)
        self.assertEqual(report["visits"], 62)
        self.assertEqual(report["automated_page_views"], 7)
        variables = post.call_args.kwargs["json"]["variables"]
        self.assertEqual(variables["audienceFilter"]["bot"], 0)
        self.assertEqual(variables["automatedFilter"]["bot"], 1)
        for key in ("audienceFilter", "automatedFilter"):
            self.assertEqual(variables[key]["siteTag"], "68b036386f3841018058c0128192ef26")
            self.assertEqual(variables[key]["requestHost"], "canecorsoancestry.com")
            self.assertEqual(variables[key]["requestPath_notlike"], "/admin/%")

    def test_permission_failure_never_becomes_zero_humans(self):
        response = Mock()
        response.json.return_value = {"errors": [{"message": "not authorized"}]}
        with patch("core.traffic.requests.post", return_value=response):
            report = get_browser_traffic("test-token", 7, datetime.now(timezone.utc))
        self.assertEqual(report["status"], "unavailable")
        self.assertNotIn("visits", report)

    def test_missing_account_is_unavailable_but_empty_groups_are_zero(self):
        for account, expected in ((None, "unavailable"), ({"audience": [], "automated": []}, "ready")):
            response = self.response(account)
            if account is None:
                response.json.return_value = {"data": {"viewer": {"accounts": []}}}
            with patch("core.traffic.requests.post", return_value=response):
                report = get_browser_traffic("test-token", 30, datetime.now(timezone.utc))
            self.assertEqual(report["status"], expected)
            if expected == "ready":
                self.assertEqual(report["visits"], 0)

    def test_rendered_audience_explains_estimates_and_never_subtracts_raw_totals(self):
        # Compile the actual dashboard through an in-memory base template.
        from pathlib import Path
        source = Path("templates/admin/website_traffic.html").read_text()
        source = source.replace("{% url 'admin-traffic' %}", "/admin/traffic/").replace("{% url 'admin:index' %}", "/admin/")
        engine = Engine(loaders=[("django.template.loaders.locmem.Loader", {
            "admin/base_site.html": "{% block content %}{% endblock %}",
            "report.html": source,
        })])
        html = engine.get_template("report.html").render(Context({"traffic": {
            "status": "ready", "days": 7, "page_views": 42000,
            "browser": {"status": "ready", "visits": 62, "page_views": 90, "automated_page_views": 7},
        }}))
        self.assertIn("Bot-filtered browser visits", html)
        self.assertIn("not unique people", html)
        self.assertIn("Raw network traffic", html)
        self.assertNotIn("Estimated unique visitors today", html)
