# Origin credential rotation (deployment phases)

The live Worker currently holds the root Django secret for the origin header.
Use a *separate, HMAC-domain-separated value* for the Cloudflare Worker so
compromising the Worker environment does not disclose Django's session-signing
root secret. Oracle derives and stores CCA_ORIGIN_EDGE_SECRET internally from
the GitHub-managed Django secret. Never log the root or derived credentials.

Phase 1 (this change): Oracle accepts both old and derived values, so existing
Cloudflare traffic remains uninterrupted. Only Oracle secrets/environment and
origin authorization behavior change. The old value is temporary.

Phase 2: Change the site-edge deployment workflow so its Worker secret file
contains only `HMAC-SHA256(DJANGO_SECRET_KEY, "cca-origin-edge-auth-v1")`.
Verify Oracle is already running Phase 1 before deploying the Worker.

Phase 3: Once live Worker requests succeed with the new value, remove the
old fallback from both Oracle and core middleware. Then inspect that the Worker
secret is derived only and is never equal to DJANGO_SECRET_KEY.

Never change Worker first: old Oracle would reject the new credential.
