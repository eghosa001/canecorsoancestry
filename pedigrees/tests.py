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
    virtual_mating_analysis,
    sibling_relationships,
)


# Virtual mating accuracy/performance coverage.
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

    def test_projected_coi_for_unrelated_founders_is_zero(self):
        sire = Dog.objects.create(name="Unrelated Sire", slug="unrelated-sire")
        dam = Dog.objects.create(name="Unrelated Dam", slug="unrelated-dam")
        self.assertAlmostEqual(projected_inbreeding(sire, dam), 0.0)

    def test_projected_coi_for_parent_offspring_pair_is_25_percent(self):
        founder_a = Dog.objects.create(name="Founder A", slug="parent-founder-a")
        founder_b = Dog.objects.create(name="Founder B", slug="parent-founder-b")
        daughter = Dog.objects.create(
            name="Founder Daughter",
            slug="founder-daughter",
            sire=founder_a,
            dam=founder_b,
        )
        self.assertAlmostEqual(projected_inbreeding(founder_a, daughter), 0.25)

    def test_projected_coi_for_full_sibling_pair_is_25_percent(self):
        father = Dog.objects.create(name="Full Father", slug="full-father")
        mother = Dog.objects.create(name="Full Mother", slug="full-mother")
        sire = Dog.objects.create(
            name="Full Brother",
            slug="full-brother",
            sire=father,
            dam=mother,
        )
        dam = Dog.objects.create(
            name="Full Sister",
            slug="full-sister",
            sire=father,
            dam=mother,
        )
        self.assertAlmostEqual(projected_inbreeding(sire, dam), 0.25)

    def test_projected_coi_for_first_cousins_is_6_point_25_percent(self):
        grandfather = Dog.objects.create(name="Cousin Grandfather", slug="cousin-grandfather")
        grandmother = Dog.objects.create(name="Cousin Grandmother", slug="cousin-grandmother")
        sibling_a = Dog.objects.create(
            name="Cousin Parent A",
            slug="cousin-parent-a",
            sire=grandfather,
            dam=grandmother,
        )
        sibling_b = Dog.objects.create(
            name="Cousin Parent B",
            slug="cousin-parent-b",
            sire=grandfather,
            dam=grandmother,
        )
        unrelated_a = Dog.objects.create(name="Cousin Other A", slug="cousin-other-a")
        unrelated_b = Dog.objects.create(name="Cousin Other B", slug="cousin-other-b")
        sire = Dog.objects.create(
            name="First Cousin Male",
            slug="first-cousin-male",
            sire=sibling_a,
            dam=unrelated_a,
        )
        dam = Dog.objects.create(
            name="First Cousin Female",
            slug="first-cousin-female",
            sire=sibling_b,
            dam=unrelated_b,
        )
        self.assertAlmostEqual(projected_inbreeding(sire, dam), 0.0625)

    def test_virtual_mating_analysis_reuses_one_graph_and_reports_common_ancestor(self):
        common = Dog.objects.create(
            name="Shared Analysis Ancestor",
            slug="shared-analysis-ancestor",
            is_public=True,
        )
        sire = Dog.objects.create(
            name="Analysis Sire",
            slug="analysis-sire",
            sex=Dog.Sex.MALE,
            sire=common,
            is_public=True,
        )
        dam = Dog.objects.create(
            name="Analysis Dam",
            slug="analysis-dam",
            sex=Dog.Sex.FEMALE,
            sire=common,
            is_public=True,
        )

        analysis = virtual_mating_analysis(sire, dam, public_only=True)

        self.assertAlmostEqual(analysis["projected_inbreeding"], 0.125)
        self.assertEqual([row["dog"].pk for row in analysis["common"]], [common.pk])
        self.assertEqual(analysis["pedigree_nodes"], 3)

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

    def test_virtual_mating_selected_ids_avoid_duplicate_name_ambiguity(self):
        sire = Dog.objects.create(
            name="Selected Sire",
            slug="selected-sire",
            sex=Dog.Sex.MALE,
            is_public=True,
        )
        chosen = Dog.objects.create(
            name="Duplicate Dam",
            slug="duplicate-dam-one",
            sex=Dog.Sex.FEMALE,
            is_public=True,
        )
        Dog.objects.create(
            name="Duplicate Dam",
            slug="duplicate-dam-two",
            sex=Dog.Sex.FEMALE,
            is_public=True,
        )

        response = self.client.get(
            reverse("pedigrees:virtual-mating"),
            {
                "sire_q": sire.name,
                "sire": str(sire.pk),
                "dam_q": chosen.name,
                "dam": str(chosen.pk),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["dam"], chosen)
        self.assertEqual(response.context["error"], "")

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
