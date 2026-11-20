# No-subscription media recovery (Oracle VM)

This is the owner-authorized fallback for inaccessible Cloudflare R2 media.
It reuses the existing private Oracle/Django site origin, rather than adding
another billed storage account. **Do not enable local media until photos are
restored.** There is no automatic way to retrieve suspended R2 objects.

## What changes

- `CCA_MEDIA_BACKEND=r2` remains the default while files are being recovered.
- `CCA_MEDIA_BACKEND=oracle-local` switches the Django default file backend
  to the persistent host directory `/var/lib/cca/media` (mounted at
  `/app/media` in the unprivileged Podman container).
- Dog images use `/media/...` and Django's existing access/consent checks.
  Private health evidence and staff-only uploads are **not** publicly exposed.
- No Cloudflare image resizing or R2 read/write calls are required for
  new locally stored media. Original full-size images may load more slowly
  than pre-generated Cloudflare WebP thumbnails.
- The Oracle VM disk is **not an offsite backup**. The new hourly fallback
  retains encrypted database snapshots on the VM; maintain an independent copy.

## Recover images without R2

An existing archive is visible in the owner's connected Google Drive:
`CaneCorsoPedigree/clean_v4_1/images/`. Its folders are named like
`121000-121999`, and an example photo filename is
`121373_ATTICUS_DI_CORTILE_CANE.jpg`. Existing imported dog media keys
are `dogs/archive/121/121373.jpg`. The recovery command uses the DB's
exact key to avoid assigning an image to the wrong dog.

1. On Oracle, check free space for both the source archive and recovered
   images: `df -h /var/lib/cca`. Keep at least several GiB free. Do not
   place the archive in Git, the Django database, or a public static folder.
2. Connect the owner's Google Drive privately using `rclone config` with
   the owner's authorization, then copy only the existing photo archive into
   `/var/lib/cca/media/.archive/clean_v4_1/images`. This auth setup
   requires the owner to approve access; never commit OAuth tokens.
3. With the new code available in a controlled Podman image/container,
   run the dry-run first:
   `CCA_MEDIA_BACKEND=oracle-local python manage.py recover_drive_archive_to_oracle /app/media/.archive/clean_v4_1/images`.
   Review the counts, then run the same command with `--write`.
   The media volume must be mounted and the production database accessed
   through the existing private network. Do not overwrite existing files.
4. For dog photos that are NOT in the archive, if R2 becomes accessible,
   `CCA_MEDIA_BACKEND=oracle-local python manage.py recover_r2_media_to_oracle`
   lists missing referenced files, and adding `--write` copies them
   without deleting R2 objects. For R2-blocked files, use owner-supplied
   backups or original images instead; do not invent replacements.
5. Check representative public and private dog photos and original
   verification documents. Validate the recovered-file coverage against
   the database before any cutover. Keep R2 originals untouched.
6. After recovery checks and off-VM backup arrangements, write a
   root-owned, nonempty `/var/lib/cca/media/.cca-media-cutover-approved`
   marker documenting the approval. The release script refuses local-media
   deployment without this marker. Do not create it merely because an
   archive directory exists; check the actual mapped photo files and
   protected documents first.
7. Set the GitHub Actions repository variable `CCA_MEDIA_BACKEND` to
   `oracle-local`. The CI-gated release and storage round-trip probe must
   pass. If its backup or media checks fail, leave the existing deployment
   intact.

## Important operational limits

- A GitHub PR does not migrate the files, change the GitHub Actions variable,
  or deploy to Oracle. No image should be reported restored until the original
  bytes have actually been copied and an HTTP image request succeeds.
- Cloudflare R2 billing suspension is a storage access restriction, not
  something a different image URL can bypass.
- Regularly check disk usage, encrypt backups, and export a second copy to
  independent storage. Same-server snapshots cannot protect against VM or
  disk loss.
- The original site uses a private Cloudflare VPC tunnel into Oracle.
  **Never open Gunicorn or PostgreSQL ports publicly.**
