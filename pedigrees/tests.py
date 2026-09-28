from django.test import TestCase

from registry.models import Dog

from .services import (
    projected_inbreeding,
    repeated_ancestors,
    sibling_relationships,
)


class PedigreeServiceTests(TestCase):
    def test_repeated_ancestor_uses_one_canonical_dog_record(self):
        common = Dog.objects.create(name="Common Ancestor", slug="common", sex=Dog.Sex.MALE)
        sire = Dog.objects.create(name="Sire", slug="sire", sire=common)
        dam = Dog.objects.create(name="Dam", slug="dam", sire=common)
        child = Dog.objects.create(name="Child", slug="child", sire=sire, dam=dam)

        repeated = repeated_ancestors(child, generations=3)

        self.assertEqual(repeated[0]["dog"].pk, common.pk)
        self.assertEqual(repeated[0]["occurrences"], 2)

    def test_half_siblings_share_one_parent(self):
        sire = Dog.objects.create(name="Shared Sire", slug="shared-sire")
        first = Dog.objects.create(
            name="First", slug="first", sire=sire, is_public=True
        )
        second = Dog.objects.create(
            name="Second", slug="second", sire=sire, is_public=True
        )

        siblings = sibling_relationships(first)

        self.assertEqual(siblings[0]["dog"], second)
        self.assertEqual(siblings[0]["relation"], "Half sibling")

    def test_projected_coi_for_half_sibling_pair_is_12_point_5_percent(self):
        common = Dog.objects.create(name="Common", slug="coi-common")
        sire = Dog.objects.create(name="Male Half Sibling", slug="male-half", sire=common)
        dam = Dog.objects.create(name="Female Half Sibling", slug="female-half", sire=common)

        self.assertAlmostEqual(projected_inbreeding(sire, dam), 0.125)
