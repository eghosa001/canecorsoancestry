"""Invalidate Django public-page metadata after committed content changes.

Cloudflare never caches database-backed pages; these LocMem entries still need
to be refreshed after an approval, moderator edit, or super-admin reversal.
"""
from django.core.cache import cache
from django.db import transaction

_PUBLIC_KEYS = (
    "cca:home:featured-dog-ids:v1",
    "cca:home:public-stats:v4",
    "cca:dog-search:default-count:v1",
    "cca:dog-search:countries:v3",
    "cca:dog-search:kennels:v3",
)


def invalidate_public_content():
    # The transaction may still roll back. Invalidate only when the approved
    # public mutation is durable to avoid showing inconsistent information.
    transaction.on_commit(lambda: cache.delete_many(_PUBLIC_KEYS))
