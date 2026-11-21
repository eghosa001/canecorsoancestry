"""Focused access control and read-only GSC metric parsing checks."""
import os
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from core.search_console import get_search_console_report


class SearchConsoleAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.owner = user_model.objects.create_superuser(
            username="gsc-owner", email="gsc-owner@example.com", password="secure-for-test-123"
        )
        cls.member = user_model.objects.create_user(
            username="gsc-member", email="gsc-member@example.com", password="secure-for-test-123"
        )

    def setUp(self):
        cache.clear()

    def test_only_superuser_can_open_search_console(self):
        url = reverse("admin-search-console")
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.owner)
        with patch.dict(os.environ, {"CCA_GSC_SERVICE_ACCOUNT_JSON": ""}):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Connect Search Console securely")
            self.assertIn("no-store", response["Cache-Control"])
            self.assertContains(self.client.get(reverse("admin:index")), url)

    def test_aggregate_rows_do_not_depend_on_hidden_queries(self):
        with patch.dict(os.environ, {
            "CCA_GSC_SERVICE_ACCOUNT_JSON": '{"type":"service_account"}',
        }):
            with patch("core.search_console.service_account.Credentials.from_service_account_info"), patch(
                "core.search_console.AuthorizedSession"
            ), patch("core.search_console._query", side_effect=[
                [{"clicks": 5, "impressions": 132, "ctr": 5 / 132, "position": 8.18}],
                [],
                [{"keys": ["https://canecorsoancestry.com/dogs/example/"], "clicks": 2, "impressions": 15, "ctr": 2 / 15, "position": 3}],
                [{"keys": ["pedigree database"], "clicks": 1, "impressions": 4, "ctr": .25, "position": 7}],
            ]) as query:
                result = get_search_console_report(28)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["clicks"], 5)
        self.assertEqual(result["impressions"], 132)
        self.assertEqual(result["ctr"], 3.79)
        self.assertEqual(len(result["daily"]), 28)
        self.assertEqual(result["queries"][0]["clicks"], 1)
        self.assertEqual(query.call_count, 4)

    def test_invalid_period_is_bounded(self):
        self.client.force_login(self.owner)
        with patch.dict(os.environ, {"CCA_GSC_SERVICE_ACCOUNT_JSON": ""}):
            response = self.client.get(reverse("admin-search-console") + "?days=90000")
        self.assertEqual(response.context["gsc"]["days"], 28)
