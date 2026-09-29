-- One-time bootstrap for Cane Corso Ancestry on Supabase.
-- Django tables live outside the exposed public schema.
create schema if not exists django_app;

revoke all on schema django_app from anon, authenticated;
alter default privileges for role postgres in schema django_app
    revoke all on tables from anon, authenticated;
alter default privileges for role postgres in schema django_app
    revoke all on sequences from anon, authenticated;
alter default privileges for role postgres in schema django_app
    revoke all on functions from anon, authenticated;

create extension if not exists pg_trgm with schema extensions;

insert into storage.buckets (
    id,
    name,
    public,
    file_size_limit,
    allowed_mime_types
)
values (
    'ancestry-private',
    'ancestry-private',
    false,
    26214400,
    array[
        'image/jpeg',
        'image/png',
        'image/webp',
        'application/pdf'
    ]::text[]
)
on conflict (id) do update
set public = excluded.public,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;
