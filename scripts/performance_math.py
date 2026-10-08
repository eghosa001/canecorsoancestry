"""Dependency-free nearest-rank percentile used by production checks."""
from math import ceil


def nearest_rank_percentile(samples, percentile=0.95):
    if not samples:
        raise ValueError("At least one sample is required.")
    if not 0 < percentile <= 1:
        raise ValueError("Percentile must be in (0, 1].")
    ordered = sorted(samples)
    return ordered[ceil(len(ordered) * percentile) - 1]
