# Production operations

The production architecture is intentionally small:

- Render: Django application and static files
- Aiven: PostgreSQL canonical database
- Cloudflare R2 gateway: uploaded dog images/documents

## Every deployment

Normal pull requests run the focused Django and Render/R2 validation workflows. UI screenshot checks run after main changes that affect UI surfaces.

After schema changes:

- migrations must pass `makemigrations --check --dry-run`;
- `python manage.py migrate --check` must report current schema in production;
- the Data Health dashboard should show zero critical relationship/date conflicts.

## Data health

Staff: `/member/moderation/data-health/`

CLI:

```bash
python manage.py audit_pedigree_data
python manage.py audit_pedigree_data --fail-on-critical
```

Critical count should remain zero. Source coverage and community-only public records should trend in the correct direction as moderation progresses.

## Scale benchmark

The benchmark is rollback-only by default and should normally run against a development/staging database:

```bash
python manage.py benchmark_scale --dogs 10000
python manage.py benchmark_scale --dogs 100000
```

It measures public search, popularity lookup and reverse-pedigree traversal without leaving synthetic dogs behind.

## Security

Authentication and contribution endpoints have cache-backed rate limits. Production responses use HSTS, secure cookies, CSRF, CSP, frame blocking and private-page no-cache/noindex rules. Passwords prefer Argon2 and existing supported hashes are upgraded when users authenticate.

When SMTP/account email is configured, set `ACCOUNT_EMAIL_ENABLED=1`. Email verification is then required by default for new member accounts unless `REQUIRE_EMAIL_VERIFICATION=0` is explicitly set. Configure `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL` and the SMTP backend before enabling it. Password-reset and verification emails are rate-limited; when account email is disabled, production uses a dummy backend rather than writing reset tokens to logs.

A scheduled Security audit workflow checks Python dependencies weekly. Keep it separate from every PR so normal development remains fast.

## Backup and recovery

A backup is only trustworthy if it restores.

Use the manual **Database recovery drill** GitHub workflow. It:

1. reads the Aiven connection secret;
2. creates a private temporary `pg_dump`;
3. restores it into an isolated PostgreSQL service;
4. verifies Django migrations;
5. runs the pedigree integrity audit;
6. deletes the temporary dump;
7. does not upload database contents as an artifact.

Run the drill after major migrations and periodically during active production use.

## Incident checks

For an application error:

1. check `/healthz/`;
2. locate the request using `X-Request-ID`;
3. review Render logs for `slow_request` or Django errors;
4. check Aiven connectivity;
5. check the R2 gateway only if media is affected;
6. review recent migrations and the moderation audit before changing canonical data.

Do not repair pedigree corruption directly in production unless the action is deliberate, auditable and backed up. Prefer a tested migration/management command.
