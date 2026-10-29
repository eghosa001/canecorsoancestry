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

## Finding the controls — layout of 29 October 2026

1. Sign in with a dedicated active staff account and open **Change center**
   in the staff workspace navigation. The page heading is **Change &
   administration center**, and the **Review queue** header also links to it.
2. Read **Your editing authority** for your current Moderator, Senior
   Moderator or Super Admin permissions. Under **How to make a change
   safely**, use the three steps: **1. Find the record**, **2. Review and
   save**, and **3. Verify the result**.
3. For the most common actions, use **Find a dog**, **Find a kennel** or
   **Review submissions**. **Staff permissions** and the header
   **Manage staff access** shortcut appear only for the Super Admin.
4. Otherwise, use **Find a setting or editable record**. The result count
   updates while typing; **Clear search** restores all available actions.
   Choose a matching category and action card, read its permissions and
   instructions, then select **Open this editor**.
5. In the destination editor, confirm the exact account or record and
   supporting evidence. Save the authorized change with a reason or source
   attestation when required. A protected ancestry proposal is *not*
   published merely because its form was submitted.
6. Reopen the saved record, relevant public profile or audit history. If
   public publication was permitted, confirm it on a **fresh page request**;
   if it was a protected proposal, check the pending approval instead.

The Change Center is a **directory of working editors**, not a universal
form that changes every website setting in place. Every individual editor
still validates role, ownership, locks, review state and accepted evidence.

Category links cover the following **actual** workflows:

- **Submissions:** Review queue → filter by dog, correction, image, health,
  document, kennel or litter; open each case; review risks, payments and evidence;
  approve, reject, request additional evidence or undertake a second review.
  The queue also supports bulk assignments, priorities, supported bulk rejections
  and individual dispute/photo corrections.
- **Dogs:** **Manage dogs** → search by name, slug, UUID or external
  registration → **Search all dogs** → **Manage record**. The new editor has
  a **Current edit** saved/unsaved indicator and four quick links:
  **Identity & ancestry** (opens **Identity & pedigree**),
  **Photos & related records** (opens **Related information**),
  **Save or submit**, and **Revision history**.
  Enter permitted identity, ancestry, photo, title, registration and source
  changes in the relevant section. Expand only the related-record groups
  needed, then choose **Save dog details and visibility** or
  **Save changes or request protected review** (button depends on authority).
  **Discard edits** reloads the editor. After saving, reopen the record
  and verify the resulting state; the on-screen unsaved indicator does
  not itself save data.
  The **Revision history and Super Admin review** disclosure is collapsed
  until opened or deep-linked; expand it to compare before/after values.
  Super Admins can also go to **Review protected proposals** from
  **Manage dogs** and open the individual pending proposal. Moderator
  changes to protected fields of published dogs require independent approval;
  do not combine these with routine edits in one save.
- **New dog:** Add Dog creates a private canonical research record. Member-paid
  listings must go through the paid submission workflow instead.
- **Health:** **Manage dogs** → search → **Health values**, or
  **Manage record** → **Review health results & values**.
  In **Add a missing health result**, select one accepted
  source, enter the exact grade/result *or* numerical value and unit, tick
  the evidence attestation, then **Save reviewed result**. Under
  **Approved health results · Edit as needed**, select **Edit health record**
  and **Save changes**, or **Hide incorrect result** as appropriate.
  A breed-composition result without owner consent may show
  **Save privately (owner consent required)** rather than publication.
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
- **Staff (Super Admin only):** **Change center** →
  **Staff permissions** (or **Manage staff access**) →
  **Verification & audit control** → expand **Staff accounts**.
  Create a dedicated staff account with **Create staff account**, or
  find the exact Admin number and username, choose **Authority** and
  press **Update role**. Suspension/restore is a *different* disclosure:
  **Moderator access** → select the account, action and reason →
  **Apply to selected moderator**. To remove a moderator permanently,
  expand **Staff accounts** → **Remove moderator permanently** on that
  specific account; enter a reason, type `DEREGISTER`, then select
  **Deregister & remove access**. The login is anonymized and disabled,
  but historical audit records are preserved.
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
