-- One-time additive archive-hypothesis columns for EXISTING dogs.
-- No dog inserted, no breeder origin overwritten, no kennel ownership granted.
-- Apply only after encrypted off-VM backup and exact Django migration allowlist.
-- Run as cca_shadow_admin; application role must not hold ALTER rights.
BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '50s';

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
    IF NOT EXISTS (
        SELECT 1 FROM django_app.django_migrations
        WHERE app = 'registry' AND name = '0015_kennel_publication_controls'
    ) THEN
        RAISE EXCEPTION 'Required publication migration is not applied';
    END IF;
    IF EXISTS (
        SELECT 1 FROM django_app.django_migrations
        WHERE app = 'registry'
          AND name = '0016_unverified_breeding_kennel_hypotheses'
    ) THEN
        RAISE EXCEPTION 'Migration already applied; manual verification required';
    END IF;
    SELECT count(*) INTO existing_count
    FROM information_schema.columns
    WHERE table_schema = 'django_app'
      AND (
        (table_name = 'registry_kennel' AND column_name = 'is_archive_hypothesis')
        OR (table_name = 'registry_dog' AND column_name IN (
            'inferred_kennel_id', 'inferred_kennel_evidence'
        ))
      );
    IF existing_count <> 0 THEN
        RAISE EXCEPTION 'Unexpected partial research schema; abort';
    END IF;
END $$;

ALTER TABLE django_app.registry_kennel
    ADD COLUMN is_archive_hypothesis boolean NOT NULL DEFAULT false;

ALTER TABLE django_app.registry_dog
    ADD COLUMN inferred_kennel_id uuid,
    ADD COLUMN inferred_kennel_evidence jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE django_app.registry_dog
    ADD CONSTRAINT cca_dog_research_kennel_fk
    FOREIGN KEY (inferred_kennel_id)
    REFERENCES django_app.registry_kennel (id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE INDEX cca_kennel_research_bool_idx
    ON django_app.registry_kennel USING btree (is_archive_hypothesis);
CREATE INDEX cca_dog_research_kennel_idx
    ON django_app.registry_dog USING btree (inferred_kennel_id);

INSERT INTO django_app.django_migrations (app, name, applied)
VALUES ('registry', '0016_unverified_breeding_kennel_hypotheses', CURRENT_TIMESTAMP);

DO $$
DECLARE
    expected_count integer;
BEGIN
    SELECT count(*) INTO expected_count
    FROM information_schema.columns
    WHERE table_schema = 'django_app'
      AND (
        (table_name = 'registry_kennel' AND column_name = 'is_archive_hypothesis'
            AND data_type = 'boolean' AND is_nullable = 'NO')
        OR
        (table_name = 'registry_dog' AND column_name = 'inferred_kennel_id'
            AND data_type = 'uuid' AND is_nullable = 'YES')
        OR
        (table_name = 'registry_dog' AND column_name = 'inferred_kennel_evidence'
            AND data_type = 'jsonb' AND is_nullable = 'NO')
      );
    IF expected_count <> 3 THEN
        RAISE EXCEPTION 'Unexpected inferred kennel column definitions';
    END IF;
    IF to_regclass('django_app.cca_dog_research_kennel_idx') IS NULL
       OR to_regclass('django_app.cca_kennel_research_bool_idx') IS NULL THEN
        RAISE EXCEPTION 'Research lookup indexes missing';
    END IF;
    IF (
        SELECT count(*) FROM django_app.django_migrations
        WHERE app = 'registry' AND name = '0016_unverified_breeding_kennel_hypotheses'
    ) <> 1 THEN
        RAISE EXCEPTION 'Migration ledger not recorded once';
    END IF;
END $$;
COMMIT;
