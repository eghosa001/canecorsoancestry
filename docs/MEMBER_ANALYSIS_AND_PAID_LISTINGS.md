# Member analysis and private-first dog submissions

- Guests can search/select parents on `/pedigrees/virtual-mating/`, but the server
  does not resolve ancestors or run virtual mating until member login. The GET
  selections survive the login/signup `next` round trip. All pedigree report,
  descendant and CSV endpoints likewise require a non-staff member account.
- Public dog profiles and the searchable pedigree index remain browseable.
  Analysis/descendant URLs are excluded from the XML sitemaps.
- New dogs use `/member/submit/dog/`: only a verified kennel's owner/editor
  may save a private submission. The `_paid_submission` flag makes a valid,
  verified Paystack payment a non-overridable moderator approval prerequisite.
  No Dog record is created by saving the draft.
- `/member/submissions/` lists the draft and provides a specific ₦500 single
  dog checkout. Checkout links that exact submission to one payment slot.
  Signed Paystack callbacks/webhooks use the existing payment verification.
  Only then may normal moderation approve and publish a canonical Dog.
- The previous prepayment multi-dog and litter workflows are retained.
  Litter package price is now ₦1,500 (existing paid checkouts remain valid).
- Run `python manage.py bootstrap_nigerian_kennel_archives` to create private
  unverified archive placeholders for Pet Palace Kennels and Ofreelife Kennels.
  This does NOT import unverifiable historical pedigree data, assert ownership
  or publish any dog. Authorized archive linkage must use the existing audited
  kennel-claim and provenance reconciliation pathways.

Focused tests: `python manage.py test accounts.tests_dog_drafts pedigrees.tests_member_gates`.
