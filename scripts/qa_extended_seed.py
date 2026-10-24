"""Additional disposable roles and image/PDF test fixtures for CI audit."""
import json
import os
import secrets
from io import BytesIO
from pathlib import Path

import django
django.setup()

from django.contrib.auth import get_user_model
from PIL import Image
from registry.models import Dog, Kennel, KennelMembership, ModerationRoleAssignment

creds_file = Path("/tmp/cca-playwright-audit-credentials.json")
data = json.loads(creds_file.read_text())
User = get_user_model()
kennel = Kennel.objects.get(slug="browser-audit-kennel")
owner = User.objects.get(pk=data["roles"]["owner"]["id"])

for role in ("member2", "editor", "contributor", "reviewer2"):
    pwd = secrets.token_urlsafe(22)
    email = f"cca.qa.{role}@example.test"
    user = User.objects.create_user(username=f"cca-audit-{role}", email=email, password=pwd)
    data["roles"][role] = {"email": email, "password": pwd, "id": user.pk}
    if role in ("editor", "contributor"):
        KennelMembership.objects.create(
            user=user, kennel=kennel,
            role=(KennelMembership.Role.EDITOR if role == "editor" else KennelMembership.Role.CONTRIBUTOR),
        )
    if role == "reviewer2":
        ModerationRoleAssignment.objects.create(
            user=user, role=ModerationRoleAssignment.Role.REVIEWER, assigned_by=owner,
        )

unclaimed = Kennel.objects.create(
    name="QA Unclaimed Ownership Kennel",
    slug="qa-unclaimed-ownership-kennel",
    country="Nigeria",
)
data["unclaimed_kennel_id"] = str(unclaimed.pk)
data["kennel_id"] = str(kennel.pk)
data["dog_id"] = str(Dog.objects.get(slug="browser-audit-sire").pk)
out = Path(os.environ["CCA_QA_FIXTURE_ROOT"])
out.mkdir(parents=True, exist_ok=True)
for name, size, color, fmt in (
    ("dog-landscape.jpg", (480, 300), (108, 84, 65), "JPEG"),
    ("dog-portrait.png", (300, 480), (55, 85, 100), "PNG"),
):
    Image.new("RGB", size, color).save(out / name, format=fmt)
Image.new("RGB", (420, 595), (255, 255, 255)).save(out / "evidence.pdf", format="PDF")
(out / "invalid-image.jpg").write_bytes(b"not a jpeg image")
data["fixtures"] = {name: str(out / name) for name in (
    "dog-landscape.jpg", "dog-portrait.png", "evidence.pdf", "invalid-image.jpg"
)}
creds_file.write_text(json.dumps(data))
creds_file.chmod(0o600)
print("QA fixtures generated: two real image formats, PDF, corrupt JPEG and separated role identities.")
