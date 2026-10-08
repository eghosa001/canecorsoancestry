import unittest

from scripts.performance_math import nearest_rank_percentile


class PercentileTests(unittest.TestCase):
    def test_twelve_samples_p95_is_slowest(self):
        self.assertEqual(nearest_rank_percentile(range(1, 13)), 12)

    def test_twenty_four_samples_p95_is_second_slowest(self):
        self.assertEqual(nearest_rank_percentile(range(1, 25)), 23)

    def test_one_sample(self):
        self.assertEqual(nearest_rank_percentile([2.5]), 2.5)

    def test_bad_inputs(self):
        with self.assertRaises(ValueError):
            nearest_rank_percentile([])
        with self.assertRaises(ValueError):
            nearest_rank_percentile([1], 0)
