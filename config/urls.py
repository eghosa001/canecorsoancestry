from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth.views import LoginView
from django.contrib.sitemaps.views import index as sitemap_index, sitemap as sitemap_view
from django.urls import include, path

from accounts.forms import EmailAuthenticationForm
from accounts.views import AccountPasswordResetView
from core.media_views import media_file
from core.sitemaps import SITEMAPS
from core.views import dashboard, healthz, home, robots_txt, storage_probe

urlpatterns = [
    path("", home, name="home"),
    path("healthz/", healthz, name="healthz"),
    path("__internal/storage-probe/", storage_probe, name="storage-probe"),
    path("robots.txt", robots_txt, name="robots"),
    path(
        "sitemap.xml",
        sitemap_index,
        {"sitemaps": SITEMAPS, "sitemap_url_name": "sitemap-section"},
        name="sitemap",
    ),
    path(
        "sitemap-<section>.xml",
        sitemap_view,
        {"sitemaps": SITEMAPS},
        name="sitemap-section",
    ),
    path("media/<path:path>", media_file, name="media-file"),
    path("dashboard/", dashboard, name="dashboard"),
    path(
        "accounts/login/",
        LoginView.as_view(authentication_form=EmailAuthenticationForm),
        name="login",
    ),
    path(
        "accounts/password_reset/",
        AccountPasswordResetView.as_view(),
        name="password_reset",
    ),
    path("accounts/", include("django.contrib.auth.urls")),
    path("member/", include("accounts.urls")),
    path("admin/", admin.site.urls),
    path("pedigrees/", include("pedigrees.urls")),
    path("", include("registry.urls")),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
