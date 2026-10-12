"""Risk and authorization regression tests for breeding kennel reconciliation."""
import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from registry.management.commands.reconcile_breeding_kennels import (
    BACKUP_CONFIRMATION,
    SOURCE_TITLE,
    _normal,
    explicit_breeding_kennel,
)
from registry.models import Dog, DogSource, Kennel, ModerationAudit


class BreedingKennelReconciliationTests(TestCase):
    def setUp(self):
        self.kennel = Kennel.objects.create(
            name="Custodinus", slug="custodinus",
            verified_at=timezone.now(),
        )
        self.buyer_kennel = Kennel.objects.create(
            name="Pet Palace", slug="pet-palace",
        )
        self.dog = Dog.objects.create(
            name="Agatha Custodinus", slug="agatha-custodinus",
            is_public=True, kennel=None,
        )

    def run_audit(self, **options):
        output = StringIO()
        with TemporaryDirectory() as temp:
            path = str(Path(temp) / "report.json")
            call_command(
                "reconcile_breeding_kennels",
                report_path=path, stdout=output, **options
            )
            self.assertTrue(Path(path).exists())
            result = json.loads(Path(path).read_text())
        return output.getvalue(), result

    def source(self, **payload):
        return DogSource.objects.create(
            dog=self.dog, title=SOURCE_TITLE,
            source_type=DogSource.SourceType.PEDIGREE,
            raw_payload=payload,
        )

    def test_only_explicit_parenthesized_breeder_is_a_breeder_proof(self):
        self.assertEqual(
            explicit_breeding_kennel("Person (Custodinus)"), "Custodinus"
        )
        self.assertFalse(explicit_breeding_kennel("Dog Custodinus"))
        self.assertFalse(explicit_breeding_kennel("Owner Custodinus"))
        self.assertFalse(explicit_breeding_kennel("Unknown (N/A)"))
        self.assertEqual(_normal("CUSTODINUS"), _normal("Custodinus"))

    def test_dry_run_never_changes_dog_when_only_name_matches(self):
        output, report = self.run_audit()
        self.dog.refresh_from_db()
        self.assertIsNone(self.dog.kennel_id)
        self.assertEqual(report["summary"]["review"], 1)
        self.assertIn("DRY RUN ONLY", output)
        self.assertEqual(report["auto_candidates"], [])
        self.assertEqual(
            report["moderator_review_candidates"][0]["suggested_kennels"][0]["name"],
            "Custodinus",
        )
        self.assertFalse(ModerationAudit.objects.exists())

    def test_owner_source_never_authorizes_breeder_link(self):
        self.source(
            owner="Custodinus", owner_id="123",
            breeder="Unknown", metadata_checked_at="2026-10-01",
        )
        output, report = self.run_audit()
        self.assertIn("DRY RUN ONLY", output)
        self.assertEqual(report["auto_candidates"], [])
        self.assertIsNone(Dog.objects.get(pk=self.dog.pk).kennel_id)

    def test_explicit_breeder_with_corroborated_source_is_eligible_only_in_dry_run(self):
        self.source(
            breeder="Origin Breeder (Custodinus)", breeder_id="555",
            kennel_evidence={"value": "Custodinus", "method": "source_breeder"},
        )
        output, report = self.run_audit()
        self.assertEqual(report["summary"]["safe"], 1)
        self.assertEqual(len(report["auto_candidates"]), 1)
        self.assertEqual(report["moderator_review_candidates"], [])
        self.assertIsNone(Dog.objects.get(pk=self.dog.pk).kennel_id)
        self.assertFalse(ModerationAudit.objects.exists())

    def test_safely_apply_only_after_offsite_backup_and_exact_reviewed_count(self):
        self.source(
            breeder="Breeder (Custodinus)", breeder_id="111",
            kennel_evidence={"value": "Custodinus", "method": "source_breeder"},
        )
        with self.assertRaisesMessage(CommandError, "backup"):
            self.run_audit(apply=True, expected_safe=1)
        with self.assertRaisesMessage(CommandError, "count"):
            self.run_audit(
                apply=True, backup_confirmation=BACKUP_CONFIRMATION,
                expected_safe=999,
            )
        output, report = self.run_audit(
            apply=True, backup_confirmation=BACKUP_CONFIRMATION,
            expected_safe=1,
        )
        self.dog.refresh_from_db()
        self.assertEqual(self.dog.kennel_id, self.kennel.pk)
        self.assertTrue(self.dog.is_public)
        self.assertIn("APPLIED: 1", output)
        audit = ModerationAudit.objects.get(
            summary__kind="verified_breeding_kennel_reconciliation",
        )
        self.assertIsNone(audit.actor)
        self.assertEqual(audit.summary["before"]["kennel_id"], None)
        self.assertEqual(audit.summary["after"]["kennel_id"], str(self.kennel.pk))

    def test_conflicting_source_evidence_requires_human_review(self):
        self.source(
            breeder="Breeder (Custodinus)", breeder_id="111",
            kennel_evidence={"value":"Pet Palace", "method":"source_breeder"},
        )
        self.source(
            breeder="Breeder (Pet Palace)", breeder_id="222",
            kennel_evidence={"value":"Pet Palace", "method":"source_breeder"},
        )
        _, report = self.run_audit()
        self.assertEqual(report["summary"]["safe"], 0)
        self.assertEqual(report["summary"]["review"], 1)
        self.assertIn(
            "conflicting_breeder_evidence",
            report["moderator_review_candidates"][0]["reason"],
        )

    def test_incomplete_documentary_evidence_never_auto_updates(self):
        self.source(
            breeder="Breeder (Custodinus)", breeder_id="111",
        )
        _, report = self.run_audit()
        self.assertEqual(report["summary"]["safe"], 0)
        self.assertEqual(report["summary"]["review"], 1)

    def test_unverified_kennel_and_super_admin_lock_always_require_review(self):
        self.source(
            breeder="Breeder (Custodinus)", breeder_id="111",
            kennel_evidence={"value": "Custodinus", "method": "source_breeder"},
        )
        self.kennel.verified_at = None
        self.kennel.save(update_fields=["verified_at"])
        _, report = self.run_audit()
        self.assertEqual(report["summary"]["safe"], 0)
        self.kennel.verified_at = timezone.now()
        self.kennel.save(update_fields=["verified_at"])
        self.dog.visibility_locked_by_superadmin = True
        self.dog.save(update_fields=["visibility_locked_by_superadmin"])
        _, report = self.run_audit()
        self.assertEqual(report["summary"]["safe"], 0)
        self.assertIsNone(Dog.objects.get(pk=self.dog.pk).kennel_id)

    def test_no_documented_breeder_stays_blank_without_auto_link(self):
        self.dog.name = "A Dog Without A Registered Kennel"
        self.dog.save(update_fields=["name"])
        output, report = self.run_audit()
        self.assertEqual(report["summary"]["unresolved"], 1)
        self.assertEqual(report["summary"]["safe"], 0)
        self.assertEqual(report["summary"]["review"], 0)
        self.assertIsNone(Dog.objects.get(pk=self.dog.pk).kennel_id)
