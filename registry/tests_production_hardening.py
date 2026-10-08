from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase

from .models import Dog, Kennel, Litter, Submission
from .services import _canonical_litter_conflict, approve_submission


class CanonicalLitterInvariantTests(TestCase):
    def setUp(self):
        self.member = get_user_model().objects.create_user(username="litter-member")
        self.reviewer = get_user_model().objects.create_user(username="litter-reviewer")
        self.kennel = Kennel.objects.create(name="Canonical Kennel", slug="canonical-kennel")
        self.sire = Dog.objects.create(
            name="Canonical Sire",
            slug="canonical-sire",
            sex=Dog.Sex.MALE,
            date_of_birth=date(2020, 1, 1),
            is_public=True,
        )
        self.dam = Dog.objects.create(
            name="Canonical Dam",
            slug="canonical-dam",
            sex=Dog.Sex.FEMALE,
            date_of_birth=date(2020, 2, 1),
            is_public=True,
        )
        self.birth_date = date(2024, 5, 10)

    def test_model_validation_rejects_second_same_parent_birth_event(self):
        Litter.objects.create(
            code="LITTER-A",
            kennel=self.kennel,
            sire=self.sire,
            dam=self.dam,
            date_of_birth=self.birth_date,
        )
        duplicate = Litter(
            code="LITTER-B",
            kennel=self.kennel,
            sire=self.sire,
            dam=self.dam,
            date_of_birth=self.birth_date,
        )

        with self.assertRaises(ValidationError):
            duplicate.full_clean()

    @patch("registry.services.verify_submission", return_value=[])
    @patch("registry.services.can_review_submissions", return_value=True)
    def test_approval_cannot_override_canonical_litter_identity(
        self,
        _can_review,
        _verify,
    ):
        existing = Litter.objects.create(
            code="LITTER-EXISTING",
            kennel=self.kennel,
            sire=self.sire,
            dam=self.dam,
            date_of_birth=self.birth_date,
            is_public=True,
        )
        submission = Submission.objects.create(
            kind=Submission.Kind.LITTER_CREATE,
            submitted_by=self.member,
            kennel=self.kennel,
            payload={
                "code": "LITTER-SECOND",
                "sire_id": str(self.sire.pk),
                "dam_id": str(self.dam.pk),
                "date_of_birth": self.birth_date.isoformat(),
            },
        )

        with self.assertRaisesRegex(ValueError, "one canonical litter"):
            approve_submission(
                submission,
                self.reviewer,
                resolution_notes="Attempted duplicate should be blocked.",
                allow_override=True,
            )

        self.assertEqual(
            Litter.objects.filter(
                sire=self.sire,
                dam=self.dam,
                date_of_birth=self.birth_date,
            ).count(),
            1,
        )
        self.assertTrue(Litter.objects.filter(pk=existing.pk).exists())


class CanonicalLitterConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.kennel = Kennel.objects.create(name="Race Kennel", slug="race-kennel")
        self.sire = Dog.objects.create(
            name="Race Sire",
            slug="race-sire",
            sex=Dog.Sex.MALE,
            date_of_birth=date(2020, 1, 1),
        )
        self.dam = Dog.objects.create(
            name="Race Dam",
            slug="race-dam",
            sex=Dog.Sex.FEMALE,
            date_of_birth=date(2020, 2, 1),
        )
        self.birth_date = date(2024, 6, 1)

    def test_parent_row_lock_serializes_concurrent_litter_creation(self):
        if connection.vendor != "postgresql":
            self.skipTest("Row-lock concurrency contract is PostgreSQL-specific.")

        barrier = Barrier(2)

        def create_or_detect(code):
            close_old_connections()
            try:
                with transaction.atomic():
                    sire = Dog.objects.get(pk=self.sire.pk)
                    dam = Dog.objects.get(pk=self.dam.pk)
                    barrier.wait(timeout=10)
                    conflict = _canonical_litter_conflict(
                        sire=sire,
                        dam=dam,
                        date_of_birth=self.birth_date,
                    )
                    if conflict is not None:
                        return "conflict"
                    Litter.objects.create(
                        code=code,
                        kennel_id=self.kennel.pk,
                        sire=sire,
                        dam=dam,
                        date_of_birth=self.birth_date,
                    )
                    return "created"
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    create_or_detect,
                    ("RACE-LITTER-A", "RACE-LITTER-B"),
                )
            )

        self.assertCountEqual(results, ["created", "conflict"])
        self.assertEqual(
            Litter.objects.filter(
                sire_id=self.sire.pk,
                dam_id=self.dam.pk,
                date_of_birth=self.birth_date,
            ).count(),
            1,
        )
