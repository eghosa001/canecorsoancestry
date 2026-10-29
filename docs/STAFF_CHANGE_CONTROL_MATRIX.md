# Staff change control — exact editor paths and authority

This policy corresponds to the authenticated **Change center** page at
`/member/moderation/change-center/`. The page lists only destinations that
the signed-in staff identity is authorized to use. It does not grant
permissions. Every action must continue checking its own server-side role,
record lock, proof, validation, risk classification and audit requirements.

## Authority

| Capability | Moderator | Senior Moderator | Super Admin |
| --- | :---: | :---: | :---: |
| Read change center and moderation queue | Yes | Yes | Yes |
| Review ordinary submissions (dogs, health, photos, kennels, documents, litters) | Yes | Yes | Yes |
| Create private research dog / change unlocked routine dog details | Yes | Yes | Yes |
| Submit changes to protected published ancestry | Proposal | Proposal | Direct/audited |
| Independently approve protected ancestry proposals | No | No | Yes |
| Approve/override red and high-risk cases; act as independent second reviewer | No | Yes | Yes |
| Correct verified medical values against accepted evidence | Yes | Yes | Yes |
| Change kennel and dog visibility not locked by Super Admin | Yes | Yes | Yes |
| Super Admin-only dog/kennel publication delegation and lock override | No | No | Yes |
| Merge duplicate dogs | No | No | Yes |
| Upload historical staff-reviewed evidence / restricted DNA records | No | No | Yes |
| Create moderators; change role; suspend/reactivate; permanently deregister | No | No | Yes |
| Change automated verification rules and lock/unlock protected dog/litter records | No | No | Yes |
| Use Django advanced admin, edit supported litter/kennel/membership models | No | No | Yes |

Dedicated staff identities must not be mixed with kennel-member identities.
An ordinary Django `is_staff` flag does not confer CaneCorsoAncestry moderation
rights. A disabled, deregistered or role-revoked account cannot edit.

## Finding the controls

1. Sign in with the correct staff account.
2. Open **Change center** in the staff workspace navigation. This is also linked
   at the top of **Review queue**; the Super Admin Django admin homepage links
   back to it.
3. Type an action into **Find a setting or editable record**, or use one of the
   category links.
4. Read the action steps, then click **Open this editor**.
5. Find the exact record or staff account, inspect evidence and current values,
   make an authorized change and save. Record the required reason/attestation.
6. Confirm the result on the canonical record, public profile or audit trail.

Category links cover the following **actual** workflows:

- **Submissions:** Review queue → filter by dog, correction, image, health,
  document, kennel or litter; open each case; review risks, payments and evidence;
  approve, reject, request additional evidence or undertake a second review.
  The queue also supports bulk assignments, priorities, supported bulk rejections
  and individual dispute/photo corrections.
- **Dogs:** Manage dogs → search name, UUID or registration → Manage record.
  Edit permitted identity fields, ancestry, related photos, registrations,
  titles, sources and visibility. Do not combine protected ancestry changes and
  ordinary edits in one save. Moderator changes to published protected fields
  become proposals; Super Admin reviews them under protected proposals.
- **New dog:** Add Dog creates a private canonical research record. Member-paid
  listings must go through the paid submission workflow instead.
- **Health:** Manage dogs → Health values. Choose an approved source, enter exact
  grade/result or numerical value plus units, attest, save. Use Edit & preview
  to correct and Hide incorrect result to suppress a wrong public summary.
  See `docs/HEALTH_RECORD_MODERATOR_WORKFLOW.md`.
- **Kennels:** Manage kennels → search → Manage publication. Confirm visibility
  actions, reason and selected dog scope. Associate existing dogs only after
  checking documentary identity; reconcile unlinked kennel candidates in the
  dedicated review tool.
- **Litters:** Members submit new litters or corrections through moderation.
  Super Admin may also use Advanced admin → Litters for supported canonical
  fields. Record locks and immutable history remain effective.
- **Verification:** The moderation queue's Advanced data tools include
  record verification. Super Admin's Verification & audit control offers
  verification rules, protected-record locks and protected proposals.
- **Staff:** Super Admin → Change center → Staff accounts. Create a dedicated
  Moderator or Senior Moderator; select an exact Admin number and username to
  update role, suspend/reactivate or permanently deregister. Permanent
  deregistration requires a reason and typing `DEREGISTER`; it disables and
  anonymizes the login **without deleting historical audit records**.
- **Other Super Admin models:** Advanced Django admin covers permitted kennel
  metadata, kennel memberships, litters, member profiles and other registered
  canonical models. It is not a shortcut around normal review.

## Changes that are NOT generally editable

- Original accepted evidence and audit history remain available for accountability.
- Payments and transaction confirmations are read-only through the supported
  admin surface and should never be fabricated or directly overwritten.
- Staff cannot create owner consent for a DNA breed-composition publication.
- A moderator cannot edit another moderator's permissions, promote themselves,
  delete staff, override protected Super Admin publication locks or sign their
  own independent high-risk second approval.
- Source code, templates, routing, SEO infrastructure, credential management,
  feature code and production deployment require a reviewed repository change
  and successful CI/deployment gates, not an arbitrary admin text field.

## Regression coverage and release gate

Run `python manage.py test accounts.tests_staff_change_center` for URL
resolution, role isolation, navigation and real staff-state mutations. The
focused CI suite also exercises staff role separation and workspace navigation.
Full release CI runs SQLite, PostgreSQL, dependency checks and browser flows.
Existing dedicated suites cover dog editing, protected proposals, kennel
visibility, health transcription, owner-DNA consent, uploads, payment
integrity, approval/publication and disputes. A successful PR merge does **not**
prove the live origin is updated: confirm the Oracle release workflow and
production release SHA before claiming deployment.

The directory itself does not create new business operations. A capability is
linked only where its real editor or approval workflow exists. Never simulate
missing rights by making a direct write outside those controls.
