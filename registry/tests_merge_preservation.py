"""Keep evidence and moderation history when retiring a duplicate pedigree dog."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from registry.models import Dog, DogIdentityNumber, DisputeCase, ModerationAudit
from registry.services import merge_dogs


class MergePreservationTests(TestCase):
    def test_merge_preserves_microchip_dispute_and_audit_links(self):
        actor = get_user_model().objects.create_user(username="merge-preservation-auditor")
        canonical = Dog.objects.create(
            name="Canonical Identity Dog", slug="canonical-identity-dog", is_public=True
        )
        duplicate = Dog.objects.create(
            name="Duplicate Identity Dog", slug="duplicate-identity-dog", is_public=True
        )
        chip = DogIdentityNumber.objects.create(
            dog=duplicate,
            kind=DogIdentityNumber.Kind.MICROCHIP,
            value="CCA-MICROCHIP-77",
        )
        dispute = DisputeCase.objects.create(
            dog=duplicate,
            opened_by=actor,
            reason=DisputeCase.Reason.DUPLICATE,
            details="Duplicate identity requires review",
        )
        audit = ModerationAudit.objects.create(
            dog=duplicate,
            actor=actor,
            action=ModerationAudit.Action.RECORD_CHANGED,
        )

        history = merge_dogs(canonical, duplicate, performed_by=actor)

        self.assertFalse(Dog.objects.filter(pk=duplicate.pk).exists())
        self.assertEqual(history.canonical_dog_id, canonical.pk)
        for row in (chip, dispute, audit):
            row.refresh_from_db()
            self.assertEqual(row.dog_id, canonical.pk)
        self.assertEqual(chip.normalized_value, "CCAMICROCHIP77")
