-- One-time, five-field, additive release of registry.0015_kennel_publication_controls.
-- Run only after a verified encrypted off-VM backup and Django migration-plan
-- allowlist. Execute as cca_shadow_admin; cca_app never receives DDL privileges.
-- Postgres rolls back every change, including migration history, on error.
BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '45s';

DO $$
DECLARE
    existing_count integer;
BEGIN
    IF current_database() <> 'cca_live' OR current_user <> 'cca_shadow_admin' THEN
        RAISE EXCEPTION 'Unexpected production database or schema administrator';
    END IF;
    IF to_regclass('django_app.registry_kennel') IS NULL
       OR to_regclass('django_app.registry_dog') IS NULL
       OR to_regclass('django_app.django_migrations') IS NULL THEN
        RAISE EXCEPTION 'Required canonical tables or migration ledger are absent';
    END IF;
    IF EXISTS (
        SELECT 1 FROM django_app.django_migrations
        WHERE app = 'registry' AND name = '0015_kennel_publication_controls'
    ) THEN
        RAISE EXCEPTION 'Migration already recorded; check version state before retry';
    END IF;
    SELECT count(*) INTO existing_count
    FROM information_schema.columns
    WHERE table_schema = 'django_app'
      AND (
        (table_name = 'registry_kennel' AND column_name IN (
            'is_public', 'hide_dogs', 'publication_locked_by_superadmin'
        )) OR
        (table_name = 'registry_dog' AND column_name IN (
            'visibility_locked_by_superadmin', 'hidden_by_moderation'
        ))
      );
    IF existing_count <> 0 THEN
        RAISE EXCEPTION 'Partial or unexpected publication schema; aborting';
    END IF;
END $$;

ALTER TABLE django_app.registry_kennel
    ADD COLUMN is_public boolean NOT NULL DEFAULT true,
    ADD COLUMN hide_dogs boolean NOT NULL DEFAULT false,
    ADD COLUMN publication_locked_by_superadmin boolean NOT NULL DEFAULT false;

ALTER TABLE django_app.registry_dog
    ADD COLUMN visibility_locked_by_superadmin boolean NOT NULL DEFAULT false,
    ADD COLUMN hidden_by_moderation boolean NOT NULL DEFAULT false;

CREATE INDEX cca_kennel_public_bool_idx
    ON django_app.registry_kennel USING btree (is_public);
CREATE INDEX cca_dog_moderation_hide_idx
    ON django_app.registry_dog USING btree (hidden_by_moderation);

INSERT INTO django_app.django_migrations (app, name, applied)
VALUES ('registry', '0015_kennel_publication_controls', CURRENT_TIMESTAMP);

DO $$
DECLARE
    expected_columns integer;
BEGIN
    SELECT count(*) INTO expected_columns
    FROM information_schema.columns
    WHERE table_schema = 'django_app'
      AND data_type = 'boolean' AND is_nullable = 'NO'
      AND (
        (table_name = 'registry_kennel' AND column_name IN (
            'is_public', 'hide_dogs', 'publication_locked_by_superadmin'
        )) OR
        (table_name = 'registry_dog' AND column_name IN (
            'visibility_locked_by_superadmin', 'hidden_by_moderation'
        ))
      );
    IF expected_columns <> 5 THEN
        RAISE EXCEPTION 'Publication fields are not five non-null booleans';
    END IF;
    IF (
        SELECT count(*) FROM django_app.django_migrations
        WHERE app = 'registry' AND name = '0015_kennel_publication_controls'
    ) <> 1 THEN
        RAISE EXCEPTION 'Publication migration ledger not exactly once';
    END IF;
    IF to_regclass('django_app.cca_kennel_public_bool_idx') IS NULL
       OR to_regclass('django_app.cca_dog_moderation_hide_idx') IS NULL THEN
        RAISE EXCEPTION 'Publication performance indexes are missing';
    END IF;
END $$;
COMMIT;
