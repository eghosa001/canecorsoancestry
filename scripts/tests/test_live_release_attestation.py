"""Release attestation must not mistake HTTP 200 or old deployments for readiness."""
from unittest import TestCase

from scripts.verify_live_release import classify_attestation, fetch_health


class ReleaseAttestationTests(TestCase):
    SHA = "a" * 40
    OLD = "b" * 40
    NOW = 1_800_000_000
    HEALTH = {
        "status": "ok", "service": "canecorsoancestry",
        "database_backend": "oracle-local", "release": SHA,
    }

    def test_matching_main_release_is_healthy(self):
        status, _ = classify_attestation(
            dict(self.HEALTH), self.SHA,
            commit_epoch=self.NOW - 9000, now_epoch=self.NOW,
        )
        self.assertEqual(status, "success")

    def test_stale_release_warns_only_during_short_deploy_grace(self):
        payload = {**self.HEALTH, "release": self.OLD}
        status, _ = classify_attestation(
            payload, self.SHA, commit_epoch=self.NOW - 100,
            now_epoch=self.NOW,
        )
        self.assertEqual(status, "warning")
        status, message = classify_attestation(
            payload, self.SHA, commit_epoch=self.NOW - 9000,
            now_epoch=self.NOW,
        )
        self.assertEqual(status, "failure")
        self.assertIn("stale", message)

    def test_retired_origin_and_unhealthy_database_always_fail_even_in_grace(self):
        for overrides in (
            {"database_backend": "supabase"},
            {"database_backend": ""},
            {"status": "unhealthy"},
            {"service": "wrong"},
        ):
            with self.subTest(overrides=overrides):
                status, _ = classify_attestation(
                    {**self.HEALTH, **overrides}, self.SHA,
                    commit_epoch=self.NOW, now_epoch=self.NOW,
                )
                self.assertEqual(status, "failure")

    def test_missing_release_does_not_pass_after_grace(self):
        status, _ = classify_attestation(
            {**self.HEALTH, "release": ""},
            self.SHA, commit_epoch=self.NOW - 10000, now_epoch=self.NOW,
        )
        self.assertEqual(status, "failure")

    def test_malformed_expected_sha_rejected(self):
        with self.assertRaises(ValueError):
            classify_attestation(self.HEALTH, "not-a-sha", commit_epoch=0)

    def test_rejects_unsafe_production_base_urls(self):
        for value in (
            "http://example.com", "https://example.com/prefix",
            "https://user:pass@example.com", "https://example.com/?debug=1",
        ):
            with self.subTest(url=value), self.assertRaises(ValueError):
                fetch_health(value)
