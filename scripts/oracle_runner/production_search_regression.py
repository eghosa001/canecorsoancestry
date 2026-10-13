"""Read-only live Oracle search probe: emit stack trace for reproducible 500s."""
from django.conf import settings
from django.test import Client

client = Client(raise_request_exception=True)
edge_key = getattr(settings, "ORIGIN_EDGE_SECRET", settings.SECRET_KEY)
host = settings.SITE_URL.split("://", 1)[-1].split("/", 1)[0]
for term in ("Branco",):
    response = client.get(
        "/dogs/",
        {"q": term},
        secure=True,
        HTTP_HOST=host,
        HTTP_X_FORWARDED_HOST=host,
        HTTP_X_FORWARDED_PROTO="https",
        HTTP_X_CCA_EDGE="1",
        HTTP_X_CCA_ORIGIN_SECRET=edge_key,
    )
    assert response.status_code == 200, f"Live Oracle dog search {term!r}: HTTP {response.status_code}"
    print(f"PASS: live Oracle dog search {term!r} HTTP 200")
