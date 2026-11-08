"""Deep-generation rendering remains complete for real ancestors, compact for empty slots."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from registry.models import Dog
from pedigrees.services import pedigree_generations


class CompactPedigreeRenderTests(TestCase):
    def test_full_ancestry_slots_preserved_but_empty_cards_bounded(self):
        dog = Dog.objects.create(name="Sparse Ten Gen Dog", slug="sparse-ten-gen", is_public=True)
        layers = pedigree_generations(dog, generations=10, public_only=True)
        self.assertEqual(len(layers), 11)
        deepest = layers[-1]
        self.assertEqual(len(deepest["nodes"]), 1024)
        self.assertEqual(len(deepest["display_nodes"]), 12)
        self.assertEqual(deepest["hidden_unknown_count"], 1012)
        self.assertEqual(sum(node["dog"] is not None for node in deepest["nodes"]), 0)

    def test_deepest_recorded_ancestor_is_never_omitted(self):
        founder = Dog.objects.create(name="Deep Founder", slug="deep-founder", is_public=True)
        subject = founder
        # Ten consecutive dams place the founder at the far end of generation 10,
        # beyond the first twelve empty slots.
        for depth in range(10):
            subject = Dog.objects.create(
                name=f"Dam Line {depth}", slug=f"dam-line-{depth}",
                dam=subject, is_public=True,
            )
        last = pedigree_generations(subject, generations=10, public_only=True)[-1]
        visible_ids = [node["dog"].pk for node in last["display_nodes"] if node["dog"]]
        self.assertIn(founder.pk, visible_ids)
        self.assertGreater(last["hidden_unknown_count"], 0)
        self.assertEqual(sum(node["dog"] is not None for node in last["nodes"]), 1)

    def test_small_generations_remain_identical(self):
        dog = Dog.objects.create(name="Small Tree", slug="small-tree", is_public=True)
        layers = pedigree_generations(dog, generations=4, public_only=True)
        for layer in layers:
            self.assertEqual(layer["display_nodes"], layer["nodes"])
            self.assertEqual(layer["hidden_unknown_count"], 0)

    def test_rendered_member_tree_discloses_omitted_unknown_positions(self):
        dog = Dog.objects.create(name="Sparse Render", slug="sparse-render", is_public=True)
        user = get_user_model().objects.create_user(
            username="compact-tree-member", password="long-pass-test-123"
        )
        self.client.force_login(user)
        result = self.client.get(reverse("pedigrees:detail", args=[dog.slug]), {"generations": 10})
        self.assertEqual(result.status_code, 200)
        self.assertContains(result, "1012 additional unknown ancestor positions omitted")
        self.assertEqual(len(result.context["layers"][-1]["nodes"]), 1024)
        self.assertEqual(len(result.context["layers"][-1]["display_nodes"]), 12)
