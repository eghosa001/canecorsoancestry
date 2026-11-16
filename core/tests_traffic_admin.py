"""Regression checks for the super-admin website traffic report."""
import os
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from core.traffic import get_traffic


@override_settings(SITE_URL="https://canecorsoancestry.com")
class WebsiteTrafficTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model()
        cls.owner = users.objects.create_superuser(
            username="traffic-owner", email="traffic-owner@example.com",
            password="test-owner-only-1234",
        )
        cls.staff = users.objects.create_user(
            username="traffic-staff", email="traffic-staff@example.com",
            password="test-staff-only-1234", is_staff=True,
        )
        cls.member = users.objects.create_user(
            username="traffic-member", email="traffic-member@example.com",
            password="test-member-only-1234",
        )

    def setUp(self):
        cache.clear()

    def test_only_superuser_may_read_traffic(self):
        url = reverse("admin-traffic")
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.staff)
        # Admin policy may redirect staff who lack super-admin authority.
        self.assertIn(self.client.get(url).status_code, (302, 403))
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.owner)
        with patch.dict(os.environ, {
            "CCA_TRAFFIC_ZONE_ID": "",
            "CCA_TRAFFIC_API_TOKEN": "",
            "CLOUDFLARE_ZONE_ID": "",
            "CLOUDFLARE_ANALYTICS_API_TOKEN": "",
        }):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Connect Cloudflare analytics")
            self.assertIn("no-store", response["Cache-Control"])
            self.assertContains(self.client.get(reverse("admin:index")), url)

    def test_readonly_api_and_metrics_are_labeled_consistently(self):
        today = datetime.now(timezone.utc).date().isoformat()
        data = {
            "data": {"viewer": {"zones": [{
                "daily": [{
                    "dimensions": {"date": today},
                    "sum": {"pageViews": 14, "requests": 82},
                    "uniq": {"uniques": 5},
                }],
                "paths": [
                    {"dimensions": {"clientRequestPath": "/dogs/zeus/"}, "count": 10},
                    {"dimensions": {"clientRequestPath": "/static/core/site.css"}, "count": 80},
                    {"dimensions": {"clientRequestPath": "/admin/"}, "count": 3},
                ],
                "countries": [
                    {"dimensions": {"clientCountryName": "Nigeria"}, "count": 40}
                ],
            }]}}
        }
        response = Mock()
        response.json.return_value = data
        env = {"CCA_TRAFFIC_ZONE_ID": "a" * 32, "CCA_TRAFFIC_API_TOKEN": "test-token"}
        with patch.dict(os.environ, env), patch(
            "core.traffic.requests.post", return_value=response
        ) as post, patch("core.traffic.get_browser_traffic", return_value={"status": "unavailable"}):
            report = get_traffic(7)
            self.assertEqual(report["status"], "ready")
            self.assertEqual(report["page_views"], 14)
            self.assertEqual(report["requests"], 82)
            self.assertEqual(report["unique_today"], 5)
            self.assertEqual(report["average_daily_uniques"], round(5 / 7, 1))
            self.assertEqual(report["paths"], [
                {"path": "/dogs/zeus/", "requests": 10}
            ])
            self.assertEqual(report["countries"][0]["name"], "Nigeria")
            self.assertEqual(post.call_args.kwargs["json"]["variables"]["host"], "canecorsoancestry.com")
            self.assertEqual(post.call_args.kwargs["timeout"], (3, 7))
            self.assertEqual(get_traffic(7), report)
            self.assertEqual(post.call_count, 1)

    def test_invalid_period_and_cloudflare_failure_are_safe(self):
        from requests import Timeout
        self.client.force_login(self.owner)
        env = {"CCA_TRAFFIC_ZONE_ID": "a" * 32, "CCA_TRAFFIC_API_TOKEN": "test-token"}
        with patch.dict(os.environ, env), patch(
            "core.traffic.requests.post", side_effect=Timeout("network error")
        ):
            response = self.client.get(reverse("admin-traffic") + "?days=5000")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Analytics temporarily unavailable")
        self.assertEqual(response.context["traffic"]["days"], 7)

