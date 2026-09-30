-- One-time database bootstrap for Cane Corso Ancestry on Supabase.
-- Django tables live outside the exposed public schema.
-- Media is stored in Cloudflare R2, not Supabase Storage.

create schema if not exists django_app;

revoke all on schema django_app from anon, authenticated;

alter default privileges for role postgres in schema django_app
    revoke all on tables from anon, authenticated;

alter default privileges for role postgres in schema django_app
    revoke all on sequences from anon, authenticated;

alter default privileges for role postgres in schema django_app
    revoke all on functions from anon, authenticated;

create extension if not exists pg_trgm with schema extensions;
