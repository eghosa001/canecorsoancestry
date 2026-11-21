"""Super-admin Search Console report, separate from Cloudflare traffic."""
from django.contrib import admin
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.views.decorators.cache import never_cache

from core.search_console import ALLOWED_DAYS, get_search_console_report


@never_cache
def search_console_admin(request):
    if not request.user.is_active or not request.user.is_superuser:
        return HttpResponseForbidden("Only super administrators can view Search Console.")
    try:
        days = int(request.GET.get("days", "28"))
    except (TypeError, ValueError):
        days = 28
    if days not in ALLOWED_DAYS:
        days = 28
    return render(request, "admin/search_console.html", {
        **admin.site.each_context(request),
        "title": "Google Search Console",
        "gsc": get_search_console_report(days),
    })
