-- One-time additive flag for revoked moderation identities.
-- Safe default FALSE preserves existing staff; no accounts, dogs or roles
-- are changed by this migration. Run only after the encrypted off-VM backup
-- and the exact migration allowlist passes.
-- Execute as cca_shadow_admin; cca_app retains no ALTER rights.
BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '50s';

DO $$
BEGIN
    IF current_database() <> 'cca_live' OR current_user <> 'cca_shadow_admin' THEN
        RAISE EXCEPTION 'Unexpected database or schema administrator';
    END IF;
    IF to_regclass('django_app.registry_moderationroleassignment') IS NULL
       OR to_regclass('django_app.django_migrations') IS NULL THEN
        RAISE EXCEPTION 'Required staff role table or migration ledger absent';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM django_app.django_migrations
        WHERE app = 'registry' AND name = '0016_unverified_breeding_kennel_hypotheses'
    ) THEN
        RAISE EXCEPTION 'Required preceding registry migration is not applied';
    END IF;
    IF EXISTS (
        SELECT 1 FROM django_app.django_migrations
        WHERE app = 'registry' AND name = '0017_moderation_staff_deregistration'
    ) THEN
        RAISE EXCEPTION 'Deregistration migration already applied';
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'django_app'
          AND table_name = 'registry_moderationroleassignment'
          AND column_name = 'is_deregistered'
    ) THEN
        RAISE EXCEPTION 'Unexpected preexisting deregistration column';
    END IF;
    IF to_regclass('django_app.cca_staff_deregistered_bool_idx') IS NOT NULL THEN
        RAISE EXCEPTION 'Unexpected preexisting staff deregistration index';
    END IF;
END $$;

ALTER TABLE django_app.registry_moderationroleassignment
    ADD COLUMN is_deregistered boolean NOT NULL DEFAULT false;

CREATE INDEX cca_staff_deregistered_bool_idx
    ON django_app.registry_moderationroleassignment USING btree (is_deregistered);

INSERT INTO django_app.django_migrations (app, name, applied)
VALUES ('registry', '0017_moderation_staff_deregistration', CURRENT_TIMESTAMP);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'django_app'
          AND table_name = 'registry_moderationroleassignment'
          AND column_name = 'is_deregistered'
          AND data_type = 'boolean'
          AND is_nullable = 'NO'
          AND column_default IN ('false', 'false::boolean')
    ) THEN
        RAISE EXCEPTION 'Deregistration flag definition invalid';
    END IF;
    IF to_regclass('django_app.cca_staff_deregistered_bool_idx') IS NULL THEN
        RAISE EXCEPTION 'Deregistration index missing';
    END IF;
    IF (
        SELECT count(*) FROM django_app.django_migrations
        WHERE app = 'registry' AND name = '0017_moderation_staff_deregistration'
    ) <> 1 THEN
        RAISE EXCEPTION 'Deregistration migration not recorded exactly once';
    END IF;
END $$;
COMMIT;
