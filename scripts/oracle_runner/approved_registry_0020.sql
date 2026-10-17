-- Privately reviewed, additive record-level public summary visibility.
-- Only after exact allowlist and encrypted offsite backup. No document exposure.
BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '50s';
DO $$
BEGIN
    IF current_database() <> 'cca_live' OR current_user <> 'cca_shadow_admin' THEN
        RAISE EXCEPTION 'Wrong administrator or production database';
    END IF;
    IF to_regclass('django_app.registry_healthrecord') IS NULL
       OR to_regclass('django_app.django_migrations') IS NULL THEN
        RAISE EXCEPTION 'Missing canonical health records or ledger';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM django_app.django_migrations
        WHERE app='registry' AND name='0019_staff_health_evidence_privacy'
    ) THEN
        RAISE EXCEPTION 'Prerequisite migration missing';
    END IF;
    IF EXISTS (
        SELECT 1 FROM django_app.django_migrations
        WHERE app='registry' AND name='0020_health_record_public_visibility'
    ) THEN
        RAISE EXCEPTION 'Visibility migration already applied';
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='django_app' AND table_name='registry_healthrecord'
          AND column_name='is_public'
    ) THEN
        RAISE EXCEPTION 'Unexpected existing public-visibility field';
    END IF;
    IF has_schema_privilege('cca_app', 'django_app', 'CREATE') THEN
        RAISE EXCEPTION 'Runtime account must not hold schema DDL rights';
    END IF;
END $$;
ALTER TABLE django_app.registry_healthrecord
    ADD COLUMN is_public boolean NOT NULL DEFAULT true;
INSERT INTO django_app.django_migrations(app,name,applied)
VALUES ('registry','0020_health_record_public_visibility',CURRENT_TIMESTAMP);
DO $$
BEGIN
    IF NOT EXISTS(
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='django_app'
          AND table_name='registry_healthrecord'
          AND column_name='is_public'
          AND data_type='boolean'
          AND is_nullable='NO'
          AND column_default IN ('true', 'true::boolean')
    ) THEN RAISE EXCEPTION 'Visibility field definition invalid'; END IF;
    IF (
        SELECT count(*) FROM django_app.django_migrations
        WHERE app='registry' AND name='0020_health_record_public_visibility'
    ) <> 1 THEN RAISE EXCEPTION 'Migration ledger not written exactly once'; END IF;
    IF has_schema_privilege('cca_app', 'django_app', 'CREATE') THEN
        RAISE EXCEPTION 'Runtime role unexpectedly has schema DDL rights';
    END IF;
END $$;
COMMIT;
