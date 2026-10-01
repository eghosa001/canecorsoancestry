from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from registry.models import Dog, HealthRecord

from .services import (
    descendant_generations,
    direct_relative_health,
    mate_relationships,
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

    def test_parent_links_automatically_create_offspring_and_descendant_relationships(self):
        sire = Dog.objects.create(
            name="Relationship Sire", slug="relationship-sire", is_public=True
        )
        child = Dog.objects.create(
            name="Relationship Child",
            slug="relationship-child",
            sire=sire,
            is_public=True,
        )

        layers = descendant_generations(sire, generations=4)

        self.assertEqual(layers[0]["dogs"], [child])

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

    def test_virtual_mating_resolves_names_without_large_dropdowns(self):
        common = Dog.objects.create(
            name="Public Common", slug="public-common", is_public=True
        )
        sire = Dog.objects.create(
            name="Searchable Sire",
            slug="searchable-sire",
            sex=Dog.Sex.MALE,
            sire=common,
            is_public=True,
        )
        dam = Dog.objects.create(
            name="Searchable Dam",
            slug="searchable-dam",
            sex=Dog.Sex.FEMALE,
            sire=common,
            is_public=True,
        )

        response = self.client.get(
            reverse("pedigrees:virtual-mating"),
            {"sire_q": sire.name, "dam_q": dam.name},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "12.50%")
        self.assertContains(response, common.name)

    def test_relative_health_is_derived_from_connected_family(self):
        sire = Dog.objects.create(
            name="Health Sire", slug="health-sire", is_public=True
        )
        child = Dog.objects.create(
            name="Health Child",
            slug="health-child",
            sire=sire,
            is_public=True,
        )
        HealthRecord.objects.create(
            dog=sire, test_type="Hips", result="Good"
        )

        rows = direct_relative_health(child)

        self.assertEqual(rows[0]["dog"], sire)
        self.assertEqual(rows[0]["relations"], ["Sire"])
        self.assertEqual(rows[0]["records"][0].result, "Good")

    def test_mates_are_derived_from_shared_offspring(self):
        sire = Dog.objects.create(
            name="Mate Sire", slug="mate-sire", sex=Dog.Sex.MALE, is_public=True
        )
        dam = Dog.objects.create(
            name="Mate Dam", slug="mate-dam", sex=Dog.Sex.FEMALE, is_public=True
        )
        Dog.objects.create(
            name="Mate Child",
            slug="mate-child",
            sire=sire,
            dam=dam,
            is_public=True,
        )

        groups = mate_relationships(sire)

        self.assertEqual(groups[0]["mate"], dam)
        self.assertEqual(groups[0]["offspring_count"], 1)

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
        self.assertGreater(analysis["ancestor_loss_percent"], 0)

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
