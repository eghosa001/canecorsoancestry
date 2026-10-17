-- Exactly three additive, privacy-preserving fields for reviewed historical tests.
-- Backup and exact allowlist gate are prerequisites; run as cca_shadow_admin only.
-- No changes to canonical dogs, previous DNA permissions or uploaded documents.
BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '50s';

DO $$
DECLARE
    found_columns integer;
BEGIN
    IF current_database() <> 'cca_live' OR current_user <> 'cca_shadow_admin' THEN
        RAISE EXCEPTION 'Unexpected production database or schema administrator';
    END IF;
    IF to_regclass('django_app.registry_healthrecord') IS NULL
       OR to_regclass('django_app.registry_dogdocument') IS NULL
       OR to_regclass('django_app.registry_breeddnareport') IS NULL
       OR to_regclass('django_app.django_migrations') IS NULL THEN
        RAISE EXCEPTION 'Required canonical tables or migration ledger are missing';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM django_app.django_migrations
        WHERE app='registry' AND name='0018_breed_dna_report'
    ) THEN
        RAISE EXCEPTION 'Previous breed DNA migration is not applied';
    END IF;
    IF EXISTS (
        SELECT 1 FROM django_app.django_migrations
        WHERE app='registry' AND name='0019_staff_health_evidence_privacy'
    ) THEN
        RAISE EXCEPTION 'Historical health privacy migration was already applied';
    END IF;
    SELECT count(*) INTO found_columns FROM information_schema.columns
    WHERE table_schema='django_app'
      AND (
          (table_name='registry_healthrecord' AND column_name='evidence_document_id')
          OR (table_name='registry_dogdocument' AND column_name='staff_review_only')
          OR (table_name='registry_breeddnareport' AND column_name='consent_public_summary')
      );
    IF found_columns <> 0 THEN
        RAISE EXCEPTION 'Unexpected preexisting/partial health privacy schema';
    END IF;
    IF to_regclass('django_app.cca_health_evidence_unique_idx') IS NOT NULL THEN
        RAISE EXCEPTION 'Unexpected existing evidence uniqueness index';
    END IF;
    IF has_schema_privilege('cca_app', 'django_app', 'CREATE') THEN
        RAISE EXCEPTION 'Runtime account must not hold schema CREATE rights';
    END IF;
END $$;

ALTER TABLE django_app.registry_healthrecord
    ADD COLUMN evidence_document_id bigint NULL;

CREATE UNIQUE INDEX cca_health_evidence_unique_idx
    ON django_app.registry_healthrecord (evidence_document_id);

ALTER TABLE django_app.registry_healthrecord
    ADD CONSTRAINT cca_health_evidence_document_fk
    FOREIGN KEY (evidence_document_id)
    REFERENCES django_app.registry_dogdocument (id)
    DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE django_app.registry_dogdocument
    ADD COLUMN staff_review_only boolean NOT NULL DEFAULT false;

-- Existing approved member DNA summaries remain authorized (migration default).
-- All NEW historical staff summaries are explicitly created with consent FALSE.
ALTER TABLE django_app.registry_breeddnareport
    ADD COLUMN consent_public_summary boolean NOT NULL DEFAULT true;

INSERT INTO django_app.django_migrations (app, name, applied)
VALUES ('registry', '0019_staff_health_evidence_privacy', CURRENT_TIMESTAMP);

DO $$
DECLARE
    found_columns integer;
BEGIN
    SELECT count(*) INTO found_columns FROM information_schema.columns
    WHERE table_schema='django_app'
      AND (
          (table_name='registry_healthrecord'
              AND column_name='evidence_document_id'
              AND data_type='bigint'
              AND is_nullable='YES')
          OR (table_name='registry_dogdocument'
              AND column_name='staff_review_only'
              AND data_type='boolean'
              AND is_nullable='NO')
          OR (table_name='registry_breeddnareport'
              AND column_name='consent_public_summary'
              AND data_type='boolean'
              AND is_nullable='NO')
      );
    IF found_columns <> 3 THEN
        RAISE EXCEPTION 'Unexpected health evidence field definitions';
    END IF;
    IF to_regclass('django_app.cca_health_evidence_unique_idx') IS NULL THEN
        RAISE EXCEPTION 'Health evidence uniqueness index missing';
    END IF;
    IF (
        SELECT count(*) FROM django_app.django_migrations
        WHERE app='registry' AND name='0019_staff_health_evidence_privacy'
    ) <> 1 THEN
        RAISE EXCEPTION 'Migration ledger not updated exactly once';
    END IF;
    IF has_schema_privilege('cca_app', 'django_app', 'CREATE') THEN
        RAISE EXCEPTION 'Runtime account acquired forbidden schema permission';
    END IF;
END $$;
COMMIT;
