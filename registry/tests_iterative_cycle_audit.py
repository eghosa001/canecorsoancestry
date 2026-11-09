"""Iterative pedigree cycle detector must survive imported deep ancestry.

Cycle checks are read-only staff audits and must never mutate canonical dogs.
"""
from unittest.mock import patch

from django.test import SimpleTestCase

from registry.data_quality import _cycles_in_parent_graph, pedigree_cycles


class IterativePedigreeCycleTests(SimpleTestCase):
    def test_deep_ancestry_avoids_python_recursion_limit(self):
        graph = {i: (i + 1,) for i in range(2500)}
        graph[2499] = ()
        self.assertEqual(_cycles_in_parent_graph(graph), [])

    def test_long_lineage_with_cycle_reports_exact_back_edge(self):
        graph = {i: (i + 1,) for i in range(1800)}
        graph[1799] = (1750,)
        found = _cycles_in_parent_graph(graph)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][0], 1750)
        self.assertEqual(found[0][-1], 1750)
        self.assertEqual(len(found[0]), 51)

    def test_normal_shared_ancestor_is_not_cycle(self):
        graph = {
            "child": ("sire", "dam"),
            "sire": ("shared_grandparent",),
            "dam": ("shared_grandparent",),
            "shared_grandparent": (),
        }
        self.assertEqual(_cycles_in_parent_graph(graph), [])

    def test_two_independent_cycles_and_limit(self):
        graph = {
            "a": ("b",),
            "b": ("a",),
            "c": ("d",),
            "d": ("c",),
        }
        self.assertEqual(_cycles_in_parent_graph(graph, limit=1), [["a", "b", "a"]])
        self.assertEqual(
            _cycles_in_parent_graph(graph, limit=2),
            [["a", "b", "a"], ["c", "d", "c"]],
        )
        self.assertEqual(_cycles_in_parent_graph(graph, limit=0), [])

    @patch("registry.data_quality.Dog.objects.values_list")
    def test_database_adapter_fetches_only_parent_ids(self, mock_values):
        mock_values.return_value = [
            ("a", "b", None),
            ("b", "a", None),
        ]
        self.assertEqual(pedigree_cycles(), [["a", "b", "a"]])
        mock_values.assert_called_once_with("id", "sire_id", "dam_id")
