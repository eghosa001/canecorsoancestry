from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from registry.models import Dog

from .services import (
    pedigree_analysis,
    pedigree_generations,
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

    def test_analysis_reports_contribution_and_linebreeding_paths(self):
        common = Dog.objects.create(name="Common", slug="analysis-common")
        sire = Dog.objects.create(name="Sire", slug="analysis-sire", sire=common)
        dam = Dog.objects.create(name="Dam", slug="analysis-dam", sire=common)
        child = Dog.objects.create(name="Child", slug="analysis-child", sire=sire, dam=dam)

        analysis = pedigree_analysis(child, generations=4)
        row = next(item for item in analysis["contributions"] if item["dog"] == common)
        line = next(item for item in analysis["linebreeding"] if item["dog"] == common)

        self.assertEqual(row["percentage"], 50.0)
        self.assertTrue(line["crosses_both_sides"])
        self.assertEqual(
            {path["label"] for path in line["paths"]},
            {"Sire → Sire", "Dam → Sire"},
        )

    def test_analysis_cache_is_revision_keyed(self):
        cache.clear()
        sire = Dog.objects.create(name="Sire", slug="cache-sire")
        child = Dog.objects.create(name="Child", slug="cache-child", sire=sire)

        first = pedigree_analysis(child, generations=4)
        second = pedigree_analysis(child, generations=4)
        sire.name = "Renamed Sire"
        sire.save()
        third = pedigree_analysis(child, generations=4)

        self.assertFalse(first["cache_hit"])
        self.assertTrue(second["cache_hit"])
        self.assertNotEqual(second["revision_key"], third["revision_key"])

    def test_ten_generation_board_batches_one_parent_query_per_generation(self):
        ancestor = Dog.objects.create(name="A0", slug="a0")
        subject = ancestor
        for index in range(1, 11):
            subject = Dog.objects.create(
                name=f"A{index}", slug=f"a{index}", sire=subject
            )

        with self.assertNumQueries(10):
            layers = pedigree_generations(subject, generations=10)

        self.assertEqual(len(layers), 11)

    def test_public_pedigree_csv_export(self):
        dog = Dog.objects.create(name="Export Dog", slug="export-dog", is_public=True)

        response = self.client.get(
            reverse("pedigrees:export", args=[dog.slug]), {"generations": 4}
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        self.assertIn("Export Dog", response.content.decode())
