-- Approved data-only visibility backfill: no DDL; no raw report publication.
-- Runs only after exact migration allowlist + verified encrypted off-VM backup.
BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '120s';

DO $$
BEGIN
  IF current_database() <> 'cca_live' OR current_user <> 'cca_shadow_admin' THEN
    RAISE EXCEPTION 'Wrong production database or administrator';
  END IF;
  IF to_regclass('django_app.registry_healthrecord') IS NULL
     OR to_regclass('django_app.registry_moderationaudit') IS NULL
     OR to_regclass('django_app.registry_breeddnareport') IS NULL
     OR to_regclass('django_app.django_migrations') IS NULL THEN
    RAISE EXCEPTION 'Required canonical tables or migration ledger absent';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM django_app.django_migrations
    WHERE app='registry' AND name='0020_health_record_public_visibility'
  ) THEN
    RAISE EXCEPTION 'Required prior migration not applied';
  END IF;
  IF EXISTS (
    SELECT 1 FROM django_app.django_migrations
    WHERE app='registry' AND name='0021_auto_publish_approved_health'
  ) THEN
    RAISE EXCEPTION 'Health publication backfill already applied';
  END IF;
  IF has_schema_privilege('cca_app', 'django_app', 'CREATE') THEN
    RAISE EXCEPTION 'Runtime account must not hold DDL privileges';
  END IF;
END $$;

-- Mirror the Python migration: a last explicit staff visibility decision
-- overrides the automatic publication default. Ignore malformed audit JSON.
WITH recent_decisions AS (
    SELECT DISTINCT ON ((a.summary->>'health_record_id')::bigint)
       (a.summary->>'health_record_id')::bigint AS health_record_id,
       CASE
         WHEN a.summary->>'kind' = 'health_summary_visibility'
              THEN a.summary->>'public'
         ELSE a.summary->'after'->>'public'
       END AS publication_choice
    FROM django_app.registry_moderationaudit a
    WHERE a.action = 'verification'
      AND a.summary->>'kind' IN (
        'health_summary_visibility', 'moderator_post_approval_health_editor'
      )
      AND (a.summary->>'health_record_id') ~ '^[0-9]{1,18}$'
      AND (
        CASE
          WHEN a.summary->>'kind' = 'health_summary_visibility'
            THEN a.summary->>'public'
          ELSE a.summary->'after'->>'public'
        END
      ) IN ('true', 'false')
    ORDER BY (a.summary->>'health_record_id')::bigint, a.id DESC
)
UPDATE django_app.registry_healthrecord record
   SET is_public = TRUE
 WHERE record.verification_state = 'health'
   AND record.is_public = FALSE
   AND NOT EXISTS (
     SELECT 1 FROM django_app.registry_breeddnareport breed
     WHERE breed.health_record_id = record.id AND breed.consent_public_summary = FALSE
   )
   AND NOT EXISTS (
     SELECT 1 FROM recent_decisions choice
     WHERE choice.health_record_id = record.id
       AND choice.publication_choice = 'false'
   );

INSERT INTO django_app.django_migrations(app,name,applied)
VALUES ('registry','0021_auto_publish_approved_health',CURRENT_TIMESTAMP);

DO $$
BEGIN
  IF (
    SELECT count(*) FROM django_app.django_migrations
    WHERE app='registry' AND name='0021_auto_publish_approved_health'
  ) <> 1 THEN
    RAISE EXCEPTION 'Migration ledger not written exactly once';
  END IF;
  IF has_schema_privilege('cca_app', 'django_app', 'CREATE') THEN
    RAISE EXCEPTION 'Runtime account gained forbidden schema DDL privilege';
  END IF;
END $$;
COMMIT;
