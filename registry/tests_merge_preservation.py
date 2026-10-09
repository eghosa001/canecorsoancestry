"""Keep evidence and moderation history when retiring a duplicate pedigree dog."""
from django.contrib.auth import get_user_model
from django.test import TestCase

from registry.models import Dog, DogImage, DogIdentityNumber, DisputeCase, ModerationAudit
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

    def test_merge_combines_photos_parents_bio_and_retains_conflicts(self):
        actor = get_user_model().objects.create_superuser(
            username="merge-photo-admin", email="merge-photo@example.com", password="test-pass"
        )
        sire = Dog.objects.create(name="Sire Test", slug="sire-test", sex=Dog.Sex.MALE)
        dam = Dog.objects.create(name="Dam Test", slug="dam-test", sex=Dog.Sex.FEMALE)
        kept = Dog.objects.create(
            name="Real Dog", slug="real-dog", colour="Black", bio="Verified history"
        )
        duplicate = Dog.objects.create(
            name="Real Dog Alternative", slug="real-dog-alt", sex=Dog.Sex.MALE,
            sire=sire, dam=dam, colour="Blue", bio="Second source history"
        )
        first = DogImage.objects.create(
            dog=kept, image="dogs/primary.jpg", is_primary=True
        )
        second = DogImage.objects.create(
            dog=duplicate, image="dogs/secondary.jpg", is_primary=True
        )
        puppy = Dog.objects.create(name="Related Puppy", slug="related-puppy", sire=duplicate)

        history = merge_dogs(kept, duplicate, performed_by=actor)

        kept.refresh_from_db()
        puppy.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(kept.sex, Dog.Sex.MALE)
        self.assertEqual(kept.sire_id, sire.pk)
        self.assertEqual(kept.dam_id, dam.pk)
        self.assertEqual(puppy.sire_id, kept.pk)
        self.assertIn("Verified history", kept.bio)
        self.assertIn("Second source history", kept.bio)
        self.assertEqual(kept.images.count(), 2)
        self.assertEqual(kept.images.filter(is_primary=True).count(), 1)
        self.assertEqual(second.image.name, "dogs/secondary.jpg")
        self.assertEqual(second.dog_id, kept.pk)
        self.assertEqual(first.dog_id, kept.pk)
        self.assertEqual(history.summary["field_conflicts"]["colour"]["kept"], "Black")
        self.assertEqual(history.summary["field_conflicts"]["colour"]["retired_record"], "Blue")
        self.assertIn("sire", history.summary["filled_fields"])
