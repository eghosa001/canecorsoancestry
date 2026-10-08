from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, F, Q
from django.db.models.functions import Lower

from accounts.models import Profile
from registry.models import (
    Dog,
    DogImage,
    Kennel,
    KennelMembership,
    Litter,
    ModerationRoleAssignment,
    Submission,
)
from registry.querysets import with_displayable_images


class Command(BaseCommand):
    help = "Audit owner-level production invariants that must never regress."

    def add_arguments(self, parser):
        parser.add_argument("--fail-on-critical", action="store_true")

    def handle(self, *args, **options):
        canonical_litter_duplicates = (
            Litter.objects.filter(
                sire__isnull=False,
                dam__isnull=False,
                date_of_birth__isnull=False,
            )
            .values("sire_id", "dam_id", "date_of_birth")
            .annotate(total=Count("id"))
            .filter(total__gt=1)
            .count()
        )

        duplicate_kennel_names = (
            Kennel.objects.annotate(name_key=Lower("name"))
            .values("name_key")
            .annotate(total=Count("id"))
            .filter(total__gt=1)
            .count()
        )

        staff_ids = ModerationRoleAssignment.objects.exclude(
            role=ModerationRoleAssignment.Role.NONE
        ).values_list("user_id", flat=True)
        staff_with_profiles = Profile.objects.filter(user_id__in=staff_ids).count()
        staff_with_kennel_membership = (
            KennelMembership.objects.filter(user_id__in=staff_ids)
            .values("user_id")
            .distinct()
            .count()
        )
        staff_with_member_submissions = (
            Submission.objects.filter(submitted_by_id__in=staff_ids)
            .values("submitted_by_id")
            .distinct()
            .count()
        )

        User = get_user_model()
        superuser_member_profiles = Profile.objects.filter(
            user__is_superuser=True
        ).count()
        superuser_kennel_memberships = (
            KennelMembership.objects.filter(user__is_superuser=True)
            .values("user_id")
            .distinct()
            .count()
        )

        litter_dob_conflicts = Dog.objects.filter(
            litter__isnull=False,
            date_of_birth__isnull=False,
            litter__date_of_birth__isnull=False,
        ).exclude(date_of_birth=F("litter__date_of_birth")).count()
        litter_sire_conflicts = Dog.objects.filter(
            litter__isnull=False,
            sire__isnull=False,
            litter__sire__isnull=False,
        ).exclude(sire_id=F("litter__sire_id")).count()
        litter_dam_conflicts = Dog.objects.filter(
            litter__isnull=False,
            dam__isnull=False,
            litter__dam__isnull=False,
        ).exclude(dam_id=F("litter__dam_id")).count()
        litter_kennel_conflicts = Dog.objects.filter(
            litter__isnull=False,
            kennel__isnull=False,
            litter__kennel__isnull=False,
        ).exclude(kennel_id=F("litter__kennel_id")).count()

        public_total = Dog.objects.filter(is_public=True).count()
        public_displayable = with_displayable_images(
            Dog.objects.filter(is_public=True)
        ).distinct().count()
        public_pedigree_only = max(0, public_total - public_displayable)

        checks = {
            "canonical_litter_duplicate_groups": canonical_litter_duplicates,
            "duplicate_kennel_name_groups": duplicate_kennel_names,
            "staff_with_member_profiles": staff_with_profiles,
            "staff_with_kennel_membership": staff_with_kennel_membership,
            "staff_with_member_submissions": staff_with_member_submissions,
            "superuser_member_profiles": superuser_member_profiles,
            "superuser_kennel_memberships": superuser_kennel_memberships,
            "litter_dob_member_conflicts": litter_dob_conflicts,
            "litter_sire_member_conflicts": litter_sire_conflicts,
            "litter_dam_member_conflicts": litter_dam_conflicts,
            "litter_kennel_member_conflicts": litter_kennel_conflicts,
        }

        self.stdout.write("Cane Corso Ancestry production invariants")
        for key, value in checks.items():
            self.stdout.write(f"- {key}: {value}")
        self.stdout.write(f"- public_dogs: {public_total}")
        self.stdout.write(f"- public_dogs_with_displayable_photo: {public_displayable}")
        self.stdout.write(f"- public_pedigree_only_records: {public_pedigree_only}")

        critical = sum(checks.values())
        self.stdout.write(f"- critical_count: {critical}")

        if options["fail_on_critical"] and critical:
            raise CommandError(
                f"Production invariants found {critical} critical issue(s)."
            )
