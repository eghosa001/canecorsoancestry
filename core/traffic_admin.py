"""Read-only Cloudflare traffic report available only to super administrators."""
from django.contrib import admin
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.views.decorators.cache import never_cache

from core.traffic import get_traffic


@never_cache
def website_traffic_admin(request):
    if not request.user.is_active or not request.user.is_superuser:
        return HttpResponseForbidden("Only super administrators can view traffic.")
    try:
        days = int(request.GET.get("days", "7"))
    except (ValueError, TypeError):
        days = 7
    if days not in (1, 7, 30):
        days = 7
    context = {
        **admin.site.each_context(request),
        "title": "Website traffic",
        "traffic": get_traffic(days),
    }
    return render(request, "admin/website_traffic.html", context)
