# Health record approval, verified values and corrections

This workflow is for authenticated Super Admins, Senior Moderators and Moderators
with active staff assignments. Member accounts cannot use the staff editor.

## Open a dog's health workspace

1. Sign in as staff and open **Moderation → Manage dog records**.
2. Search for the dog's name or ID. Use **Health values** next to the result,
   or open **Manage record → Review health results & values**.
3. Alternatively, go to `/moderation/health-results/<dog UUID>/` while
   authenticated. Always confirm the exact dog first.

## When a Health/DNA submission is approved

1. Open **Moderation → Health uploads → Review certificate**.
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

1. Open the dog's **Review health results & values** workspace.
2. Under **Add a condition from an approved report**, choose **Or approved
   Health/DNA document** and select the accepted PDF/image. Do not select two
   sources at once.
3. Enter the exact **test/condition name**, **result or grade**, and **test
   date** if the report gives one.
4. For plain decimal measurements, leave **Result / grade** empty and enter
   **Exact numeric value** and, if appropriate, **Measurement unit**.
   The application saves these together as the reported result; for example
   `12.50` and `mm` are stored as `12.50 mm`. Zero is valid.
5. For grades, labels and compound scores, use the **Result / grade** field
   directly: `HD-A`, `ED-0`, `12/24`, `Clear`, `Carrier`, etc. Do not
   simultaneously fill the numeric field.
6. Tick the attestation confirming the exact value was checked against the
   approved certificate, then **Save reviewed result**.
7. The new result is immediately marked **Health/DNA verified**, is audited,
   and its textual summary appears on the dog's profile if that dog is
   published. The certificate is not publicly exposed.

Every additional value from the same source must be entered as a separate
condition, using the same approved document. Don't guess grades, test dates,
reference ranges, numbers or units absent from the report.

## Correcting or hiding a saved value

1. Open the dog's **Review health results & values**.
2. Find the verified record and choose **Edit & preview**.
3. Open the confidential evidence link and compare the recorded result.
4. Change the **Result / grade** field directly, or clear its existing text
   and use **Exact numeric measurement** plus **Measurement unit**.
5. Tick the review attestation. Choose **Save corrections**. The corrected
   result stays verified, and the audit retains the before/after values.
6. To suppress an incorrect result, choose **Hide incorrect result** on the
   list; this hides the public summary without deleting evidence or
   verification history. Staff can restore publication once the value is
   corrected, subject to the DNA consent requirements.

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
