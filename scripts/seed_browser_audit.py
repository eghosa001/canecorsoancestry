"""Create isolated Playwright audit accounts in the CI-only SQLite database."""
import json
import secrets
from pathlib import Path

import django

django.setup()

from django.contrib.auth import get_user_model
from django.utils import timezone
from registry.models import Dog, Kennel, KennelMembership, ModerationRoleAssignment, Submission

U = get_user_model()
roles = {}
owner = None
for role in ("member", "moderator", "senior", "owner"):
    password = secrets.token_urlsafe(22)
    username = f"cca-browser-{role}"
    email = f"{username}@example.invalid"
    if role == "owner":
        user = U.objects.create_superuser(username=username, email=email, password=password)
        owner = user
    else:
        user = U.objects.create_user(username=username, email=email, password=password)
    roles[role] = {"email": email, "password": password, "id": user.pk}
    if role == "owner":
        ModerationRoleAssignment.objects.create(
            user=user, role=ModerationRoleAssignment.Role.OWNER, assigned_by=user
        )

for role, staff_role in (
    ("moderator", ModerationRoleAssignment.Role.REVIEWER),
    ("senior", ModerationRoleAssignment.Role.SENIOR),
):
    ModerationRoleAssignment.objects.create(
        user=U.objects.get(pk=roles[role]["id"]),
        role=staff_role,
        assigned_by=owner,
    )

kennel = Kennel.objects.create(
    name="Browser Audit Kennel", slug="browser-audit-kennel", country="Nigeria",
    verified_at=timezone.now(),
)
KennelMembership.objects.create(
    user=U.objects.get(pk=roles["member"]["id"]),
    kennel=kennel,
    role=KennelMembership.Role.OWNER,
)
sire = Dog.objects.create(
    name="Browser Audit Sire", slug="browser-audit-sire",
    sex=Dog.Sex.MALE, is_public=True, kennel=kennel,
)
dam = Dog.objects.create(
    name="Browser Audit Dam", slug="browser-audit-dam",
    sex=Dog.Sex.FEMALE, is_public=True, kennel=kennel,
)
Dog.objects.create(
    name="Browser Audit Offspring", slug="browser-audit-offspring",
    sex=Dog.Sex.FEMALE, sire=sire, dam=dam, is_public=True, kennel=kennel,
)
Dog.objects.create(
    name="Browser Audit Private", slug="browser-audit-private",
    sex=Dog.Sex.MALE, is_public=False, kennel=kennel,
)
submission = Submission.objects.create(
    kind=Submission.Kind.KENNEL_CREATE,
    submitted_by=U.objects.get(pk=roles["member"]["id"]),
    payload={"name": "Browser Pending Kennel", "slug": "browser-pending-kennel"},
)
payload = {"roles": roles, "submission_id": str(submission.pk)}
path = Path("/tmp/cca-playwright-audit-credentials.json")
path.write_text(json.dumps(payload))
path.chmod(0o600)
print("Created four separate ephemeral role identities, published/private dogs, and one review submission.")
