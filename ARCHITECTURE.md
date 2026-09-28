# Architecture

## Stack

Cane Corso Ancestry is a Django application.

Primary production stack:

- Python 3.13
- Django 5.2
- PostgreSQL
- Django templates for server-rendered pages
- HTMX/Alpine.js or small vanilla JavaScript only where interaction benefits from it
- WhiteNoise for static assets in simple deployments
- object storage for production media/evidence when deployment is configured
- Gunicorn or equivalent WSGI/ASGI hosting
- GitHub Actions for targeted checks

The public experience should remain usable without a heavy JavaScript application shell.

## Current Django apps

### `core`

Site shell, homepage, shared navigation and later the custom member dashboard.

### `accounts`

Member profile and account-specific features.

### `registry`

Internal code package for canonical dog, kennel, litter, image, health, source and external-registration records.

The package name is internal only. **The public product must not be presented as a registry.**

### `pedigrees`

Pedigree traversal, repeated-ancestor analysis, common-ancestor analysis, COI calculations and virtual mating.

## Core record graph

`Dog` is the canonical node.

Each dog can reference:
- one sire;
- one dam;
- one kennel;
- one litter;
- aliases;
- external registrations;
- images;
- health records;
- evidence/sources.

Repeated appearances of one ancestor in a rendered pedigree do not create extra Dog rows.

## Database rules

Use PostgreSQL in production.

Use constraints for facts that must be unique or singular, including:
- one kennel membership per user/kennel pair;
- one external registration number per authority;
- one primary image per dog;
- unique canonical slugs.

Pedigree code must be cycle-safe. A malformed ancestry cycle must not recurse forever.

## Search

Public search should eventually support:

- canonical name;
- aliases;
- kennel;
- breeder where supplied;
- external registration number;
- sex;
- country;
- colour;
- date range;
- health/DNA attributes;
- verification state.

Fuzzy matching should be introduced only with safeguards against accidental duplicate creation.

## Member and moderator separation

Normal breeders/members receive a custom dashboard matching the supplied member reference.

Raw Django Admin is an internal moderation/operations tool and is not the normal member experience.

Expected roles:

- member;
- kennel contributor;
- kennel editor;
- kennel owner;
- moderator/admin.

Permissions must be enforced server-side, not only by hiding controls.

## Verification

Verification is evidence-scoped.

Suggested progression:

1. Community submitted
2. Source attached
3. Identity reviewed
4. Pedigree reviewed
5. Health/DNA verified

A kennel has a separate verification state.

## Pedigree analysis

The analysis layer should provide deterministic services independent from templates:

- bounded pedigree traversal;
- repeated ancestor detection;
- full/half sibling discovery;
- offspring queries;
- common ancestor detection;
- inbreeding coefficient calculations;
- projected virtual-mating coefficient.

Calculation code should have short unit tests with small known pedigrees.

## Media

Original uploaded media is the source of truth.

Do not repeatedly recompress dog photography. Preserve dimensions and aspect ratio.

Profile/ancestry imagery must avoid cropping faces, ears or important body features merely to fill a card.

Evidence documents must not be exposed publicly unless explicitly intended for public viewing.

## Deployment

Production settings require:

- `DJANGO_SECRET_KEY`;
- `DATABASE_URL`;
- explicit allowed hosts;
- trusted CSRF origins when needed;
- HTTPS;
- secure cookies.

The final hosting provider can be selected later without changing the product/data model.

## CI philosophy

Keep CI focused and fast:

- migration drift check;
- `manage.py check`;
- short Django unit tests;
- later, a small Playwright responsive smoke suite.

Do not run expensive unrelated suites for narrow changes.
