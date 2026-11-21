"""Small, cached Search Console summary for the Django admin landing page."""
from django import template

from core.search_console import get_search_console_report

register = template.Library()


@register.simple_tag(takes_context=True)
def gsc_admin_summary(context):
    request = context.get("request")
    if request is None or not request.user.is_active or not request.user.is_superuser:
        return {"status": "forbidden"}
    return get_search_console_report(28)
