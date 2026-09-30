import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.cloudflare")

from django.core.wsgi import get_wsgi_application
from workers import wsgi

application = get_wsgi_application()
Default = wsgi.entrypoint(application)
