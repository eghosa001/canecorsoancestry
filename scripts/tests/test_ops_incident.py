"""The incident automation must not post on PRs, skips, cancelled runs or foreign repos."""
from unittest import TestCase
from scripts.ops_incident import REPOSITORY, eligible_run, incident_title


def event(**kwargs):
    return {"workflow_run": {
        "name": "Production availability watch", "status": "completed",
        "conclusion": "failure", "head_branch": "main",
        "head_repository": {"full_name": REPOSITORY},
        "event": "schedule", "html_url": "https://github.com/example/runs/1",
        **kwargs,
    }}


class OperationalIssueSafetyTests(TestCase):
    def test_scheduled_failure_and_recovery_eligible(self):
        self.assertTrue(eligible_run(event(), REPOSITORY))
        self.assertTrue(eligible_run(event(conclusion="success"), REPOSITORY))
        self.assertEqual(incident_title("Oracle R2 backup freshness watch"),
                         "[CCA operational alert] Oracle R2 backup freshness watch")

    def test_untrusted_or_nonincident_runs_are_ignored(self):
        for changes, repo in (
            ({}, "other/repository"),
            ({"event": "pull_request"}, REPOSITORY),
            ({"head_branch": "feature"}, REPOSITORY),
            ({"head_repository": {"full_name": "other/repository"}}, REPOSITORY),
            ({"status": "in_progress"}, REPOSITORY),
            ({"conclusion": "skipped"}, REPOSITORY),
            ({"conclusion": "cancelled"}, REPOSITORY),
            ({"name": "Dangerous unrelated workflow"}, REPOSITORY),
        ):
            with self.subTest(changes=changes, repo=repo):
                self.assertFalse(eligible_run(event(**changes), repo))
