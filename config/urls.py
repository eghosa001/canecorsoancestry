from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path

from core.media_views import media_file, media_import
from core.sitemaps import SITEMAPS
from core.views import dashboard, healthz, home, robots_txt

urlpatterns = [
    path("", home, name="home"),
    path("healthz/", healthz, name="healthz"),
    path("robots.txt", robots_txt, name="robots"),
    path("sitemap.xml", sitemap, {"sitemaps": SITEMAPS}, name="sitemap"),
    path("media/<path:path>", media_file, name="media-file"),
    path(
        "internal/media-import/<path:path>",
        media_import,
        name="media-import",
    ),
    path("dashboard/", dashboard, name="dashboard"),
    path("accounts/", include("django.contrib.auth.urls")),
    path("member/", include("accounts.urls")),
    path("admin/", admin.site.urls),
    path("pedigrees/", include("pedigrees.urls")),
    path("", include("registry.urls")),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
