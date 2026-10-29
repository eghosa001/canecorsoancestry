# Health record approval, verified values and corrections

This workflow is for authenticated Super Admins, Senior Moderators and Moderators
with active staff assignments. Member accounts cannot use the staff editor.

## Starting from Audit history (including older verified records)

Audit history shows immutable evidence of the original decision; it is not the editor.
After signing in as Super Admin, Senior Moderator or Moderator, open **Audit history**
and find the entry for the dog. Use **Edit dog details** for the canonical dog
record or **Edit health records** to see every available health result. Entries
for independently reviewed historical health evidence also offer
**Edit this verified result**, which opens the exact evidence-verified result.
No new member request is required for an authorized staff correction.

Use **Edit health record** to check the original evidence and save the corrected
health values. The original audit entry and certificate remain unchanged.
The shortcut is absent if the dog itself has been removed; old audit
entries remain readable.

## Open a dog's health workspace

1. Sign in with an active dedicated staff account and use the
   **Change center** link in the staff workspace.
2. Under **How to make a change safely**, choose **Find a dog**, or search
   for **Enter or change verified health numbers** under
   **Find a setting or editable record**, then click **Open this editor**.
   Alternatively use the **Manage dogs** link in the staff navigation.
3. On **Manage dog records**, enter a name, registration, slug or UUID and
   click **Search all dogs**. For the exact dog choose **Health values**.
   Alternatively, choose **Manage record**, then
   **Review health results & values** near the top of the dog editor.
4. The canonical dog editor now has quick links for
   **Identity & ancestry**, **Photos & related records**, **Save or submit**
   and **Revision history**. The health-result editor is a **separate
   page**, not a tab under **Identity & ancestry**.
5. The exact authenticated health-results route is
   `/member/moderation/health-results/<dog UUID>/` (replace the placeholder
   with the dog's UUID). Always confirm the dog's name before modifying data.

## When a Health/DNA submission is approved

1. Open **Review queue** → choose **Health uploads** (or filter **Type**
   for health), then select **Open review** or **Review warnings** on the
   matching submission. Alternatively, **Health values** for the dog shows
   **New laboratory evidence** with a **Review certificate** link.
2. Read the original private PDF/image and, when relevant, transcribe supported
   genetic markers before approval. Use the existing risk-based approval flow
   (high-risk submissions can require a second reviewer).
3. Upon final approval, the saved HealthRecord is **Health/DNA verified**
   (`verification_state=health`). Its result summary is automatically visible
   on the profile of a public dog. The underlying certificate stays private.
4. Open **Review health results & values** to add missing findings or correct a
   reported number. The existing verified record stays verified after an
   audited correction.

## When a general Health/DNA document was already accepted

Acceptance of a generic document verifies the **source was accepted**, not
unknown measurements that have not been transcribed yet. To enter the findings:

1. Open the dog's **Health values** workspace from **Manage dog records**
   or use **Review health results & values** from **Manage record**.
2. Under **Add a missing health result**, choose **Or approved
   Health/DNA document** and select the accepted PDF/image. Do not select two
   sources at once.
3. Enter **Exact genetic condition / test name**,
   **Result / grade exactly as reported**, and **Test date** if supplied.
4. For plain decimal measurements, leave **Result / grade exactly as reported**
   empty and enter **Exact numeric value (optional)** and, if appropriate,
   **Measurement unit (optional)**.
   The application saves these together as the reported result; for example
   `12.50` and `mm` are stored as `12.50 mm`. Zero is valid.
5. For grades, labels and compound scores, use the
   **Result / grade exactly as reported** field
   directly: `HD-A`, `ED-0`, `12/24`, `Clear`, `Carrier`, etc. Do not
   simultaneously fill the numeric field.
6. Tick **I have checked this additional condition and its result in the
   approved report**, then select **Save reviewed result**.
7. The new result is immediately marked **Health/DNA verified**, is audited,
   and its textual summary appears on the dog's profile if that dog is
   published. The certificate is not publicly exposed.

Every additional value from the same source must be entered as a separate
condition, using the same approved document. Don't guess grades, test dates,
reference ranges, numbers or units absent from the report.

## Why the approved submission is read-only, and how to correct the saved result

**Approval does not lock the health result forever.** The original submission,
certificate, evidence and review decision are immutable to preserve an audit trail.
The **HealthRecord** (the verified text shown to visitors) is corrected separately.

- From an approved **Health/DNA submission**, open the case and select
  **Edit approved health values**. This opens **Approved health results ·
  Edit as needed** for that dog.
- From the public dog profile while signed in as staff, select
  **Edit verified health values** in **Health & DNA**.
- Or go through **Manage dogs → Search all dogs → Health values**.
  Select the relevant **Edit health record** control, review the original
  evidence, change the exact value, check the attestation, and
  choose **Save changes**.
- An approved **Health/DNA document** is accepted source evidence; it
  does not invent measurements. Open **Enter or correct values from this
  approved report** and transcribe each actual finding under
  **Add a missing health result** before it can be edited
  as a verified value.
- Older records marked **Community submitted** or similar are *not*
  evidence-verified and do not have an approved-result correction button.
  Review and accept the appropriate source first. Never silently upgrade a
  legacy claim to a verified test result.

After each correction, refresh the staff results and the dog's public
profile. The new value is persisted, the result remains evidence-verified
unless a different review action was taken, and the original submission
and private source documents remain unchanged. Multiple corrections
are permitted, with independent audit entries.

## Correcting or hiding a saved value

1. Open the dog's **Health values** workspace or
   **Review health results & values** from **Manage record**.
2. Under **Approved health results · Edit as needed**, find the verified
   record and choose **Edit health record**.
3. On the edit page, compare **01 · Verified evidence** with the confidential
   original source, then examine **02 · Public preview**.
4. Under **03 · Correction**, change **Reported result / grade** directly,
   or clear the existing grade and use **Exact numeric measurement (optional)**
   plus **Measurement unit (optional)**.
5. Tick **I checked the edited public summary against the original laboratory
   evidence**, then select **Save changes** when publication is permitted.
   Where owner consent for breed composition is missing, the screen instead
   offers **Save privately (owner consent required)**; it does *not* authorize
   publishing a DNA breed-composition summary. The audit retains the edit.
6. To suppress a published incorrect result, return to
   **Approved health results · Edit as needed** and choose
   **Hide incorrect result**. This hides the public summary without deleting
   its evidence or audit history. Restoring visibility remains subject to
   publication restrictions and owner DNA consent.

## Important boundaries

- A document is not proof of an unspecified test, score or negative result.
  Staff must read and faithfully transcribe each accepted finding.
- `DSRA`, `NCL1` and `CMR1` must use the actual report status
  (Clear, Carrier, Affected, Inconclusive or Not tested where supported);
  do not reinterpret an arbitrary numeric measurement as genetic clearance.
- DNA **breed composition** is different from clinical Health/DNA results:
  percentages are entered in the separate breed-report form, must total
  100%, and cannot be published without the owner's explicit summary consent.
- Published dog profiles display result summaries only. Accepted laboratory
  source documents used for transcription are private.
- All source links are dog-specific, the staff permission is checked on the
  server, and a successful edit is recorded in the moderation audit.
