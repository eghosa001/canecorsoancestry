import { driveArchiveIds } from "./drive-archive-map.js";

const encoder = new TextEncoder();
const decoder = new TextDecoder();

function bytesToHex(bytes) {
  return Array.from(new Uint8Array(bytes))
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
}

async function sha256Hex(data) {
  return bytesToHex(await crypto.subtle.digest("SHA-256", data));
}

async function hmacHex(secret, message) {
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return bytesToHex(
    await crypto.subtle.sign("HMAC", key, encoder.encode(message)),
  );
}

function constantTimeEqual(left, right) {
  if (typeof left !== "string" || typeof right !== "string") return false;
  if (left.length !== right.length) return false;
  let mismatch = 0;
  for (let index = 0; index < left.length; index += 1) {
    mismatch |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }
  return mismatch === 0;
}

function safeKey(url, prefix) {
  const encoded = url.pathname.slice(prefix.length);
  let key;
  try {
    key = decodeURIComponent(encoded);
  } catch {
    return null;
  }
  if (!key || key.startsWith("/") || key.split("/").includes("..")) {
    return null;
  }
  return key;
}

function isAllowedSourceUrl(source) {
  return (
    source instanceof URL &&
    (source.hostname === "www.canecorsopedigree.com" ||
      source.hostname === "canecorsopedigree.com") &&
    source.pathname.startsWith("/static/images/animal/") &&
    source.protocol === "https:" &&
    (!source.port || source.port === "443") &&
    !source.username &&
    !source.password
  );
}

async function fetchAllowedSource(source, options, maxRedirects = 3) {
  let current = source;
  for (let redirects = 0; redirects <= maxRedirects; redirects += 1) {
    const response = await fetch(current.toString(), {
      ...options,
      redirect: "manual",
    });
    if (![301, 302, 303, 307, 308].includes(response.status)) {
      return response;
    }
    if (redirects === maxRedirects) {
      throw new Error("Too many source redirects");
    }
    const location = response.headers.get("location");
    if (!location) {
      throw new Error("Source redirect did not include a location");
    }
    let next;
    try {
      next = new URL(location, current);
    } catch {
      throw new Error("Source redirect location is invalid");
    }
    if (!isAllowedSourceUrl(next)) {
      throw new Error("Source redirect is outside the allowed image host/path");
    }
    current = next;
  }
  throw new Error("Source redirect limit exceeded");
}

function r2Headers(object, cacheControl = "private, no-store") {
  const headers = new Headers();
  if (object.writeHttpMetadata) object.writeHttpMetadata(headers);
  if (object.httpEtag) headers.set("etag", object.httpEtag);
  if (typeof object.size === "number") {
    headers.set("content-length", String(object.size));
  }
  headers.set("cache-control", cacheControl);
  headers.set("x-content-type-options", "nosniff");
  const contentType = headers.get("content-type") || "";
  if (contentType === "application/pdf") {
    headers.set("content-disposition", "attachment");
  }
  return headers;
}

async function verifyGatewayRequest(request, env, key, body) {
  const timestamp = request.headers.get("x-r2-timestamp") || "";
  const digest = request.headers.get("x-r2-content-sha256") || "";
  const signature = request.headers.get("x-r2-signature") || "";

  if (!/^\d+$/.test(timestamp)) return { ok: false, reason: "timestamp_format" };
  const now = Math.floor(Date.now() / 1000);
  if (Math.abs(now - Number(timestamp)) > 300) {
    return { ok: false, reason: "timestamp_skew" };
  }

  const actualDigest = await sha256Hex(body);
  if (!constantTimeEqual(actualDigest, digest)) {
    return { ok: false, reason: "digest" };
  }

  const wireMethod = request.method.toUpperCase();
  const signingKey = env.R2_GATEWAY_SIGNING_KEY || env.DJANGO_SECRET_KEY;
  const expected = await hmacHex(
    signingKey, [wireMethod, key, timestamp, digest].join("\n"),
  );
  if (constantTimeEqual(expected, signature)) {
    return { ok: true, reason: "ok", method: wireMethod };
  }
  // Cloudflare may internally convert HEAD into GET when handling a cold
  // cache entry. Verify the *HEAD* HMAC, but retain its limited authority:
  // such a request must NEVER be allowed to download the object body.
  if (wireMethod === "GET") {
    const signedHead = await hmacHex(
      signingKey, ["HEAD", key, timestamp, digest].join("\n"),
    );
    if (constantTimeEqual(signedHead, signature)) {
      return { ok: true, reason: "head_promoted_to_get", method: "HEAD" };
    }
  }
  return { ok: false, reason: "signature", method: wireMethod };
}

async function handleR2Gateway(request, env, url, ctx) {
  const key = safeKey(url, "/_r2/");
  if (!key) return new Response("Invalid key", { status: 400 });

  const body = request.method === "PUT"
    ? await request.arrayBuffer()
    : new ArrayBuffer(0);

  const verification = await verifyGatewayRequest(request, env, key, body);
  if (!verification.ok) {
    return Response.json(
      { status: "forbidden", reason: verification.reason },
      {
        status: 403,
        headers: {
          "cache-control": "private, no-store",
          "x-r2-auth-reason": verification.reason,
          "x-r2-auth-method": verification.method || request.method.toUpperCase(),
        },
      },
    );
  }

  if (verification.method === "GET") {
    const archived = await originalDriveArchivePhoto(key, "GET");
    if (archived) return archived;
    const object = await env.MEDIA_BUCKET.get(key);
    if (!object) return new Response("Not found", {
      status: 404,
      headers: { "cache-control": "private, no-store" },
    });
    return new Response(object.body, {
      status: 200,
      headers: r2Headers(object),
    });
  }

  if (verification.method === "HEAD") {
    const archived = await originalDriveArchivePhoto(key, "HEAD");
    if (archived) return archived;
    const object = await env.MEDIA_BUCKET.head(key);
    if (!object) return new Response(null, {
      status: 404,
      headers: { "cache-control": "private, no-store" },
    });
    return new Response(null, {
      status: 200,
      headers: r2Headers(object),
    });
  }

  if (request.method === "PUT") {
    const stored = await env.MEDIA_BUCKET.put(key, body, {
      httpMetadata: {
        contentType:
          request.headers.get("content-type") || "application/octet-stream",
      },
    });

    const verified = await env.MEDIA_BUCKET.head(key);
    if (!verified || verified.size !== body.byteLength) {
      await env.MEDIA_BUCKET.delete(key);
      return Response.json(
        {
          status: "r2_verify_failed",
          key,
          expected_size: body.byteLength,
          actual_size: verified ? verified.size : null,
        },
        { status: 500 },
      );
    }

    // A replaced original must never leave the previously derived WebP
    // visible at the stable private key. Delete before prewarming.
    if (isPhotoKey(key)) await invalidateDirectPhotoRenditions(env, key);
    // New dog photographs are rendered once in the background after their
    // original R2 upload is verified. Visitors can then fetch small WebP
    // previews immediately rather than waiting for a cold conversion.
    if (isPhotoKey(key)) {
      const warm = prewarmUploadedDogPhoto(
        env, key, verified.httpEtag || stored.httpEtag, body,
      );
      if (ctx && typeof ctx.waitUntil === "function") ctx.waitUntil(warm);
      else await warm;
    }
    return Response.json(
      {
        status: "stored",
        key,
        size: verified.size,
        etag: stored.httpEtag,
        r2_verified: true,
      },
      { status: 201 },
    );
  }

  if (request.method === "DELETE") {
    await env.MEDIA_BUCKET.delete(key);
    if (isPhotoKey(key)) await invalidateDirectPhotoRenditions(env, key);
    return new Response(null, { status: 204 });
  }

  return new Response("Method not allowed", {
    status: 405,
    headers: { allow: "GET,HEAD,PUT,DELETE" },
  });
}

async function handleR2Ingest(request, env, url, ctx) {
  if (request.method !== "POST") {
    return new Response("Method not allowed", {
      status: 405,
      headers: { allow: "POST" },
    });
  }

  const key = safeKey(url, "/_r2_ingest/");
  if (!key) return new Response("Invalid key", { status: 400 });

  const body = await request.arrayBuffer();
  const verification = await verifyGatewayRequest(request, env, key, body);
  if (!verification.ok) {
    return Response.json(
      { status: "forbidden", reason: verification.reason },
      {
        status: 403,
        headers: {
          "cache-control": "private, no-store",
          "x-r2-auth-reason": verification.reason,
          "x-r2-auth-method": verification.method || request.method.toUpperCase(),
        },
      },
    );
  }

  let payload;
  try {
    payload = JSON.parse(decoder.decode(body));
  } catch {
    return new Response("Invalid JSON", { status: 400 });
  }

  let source;
  try {
    source = new URL(String(payload.url || ""));
  } catch {
    return new Response("Invalid source URL", { status: 400 });
  }

  if (!isAllowedSourceUrl(source)) {
    return new Response("Source URL not allowed", { status: 400 });
  }

  const expectedSize = Number(payload.expected_size || 0);
  if (!Number.isSafeInteger(expectedSize) || expectedSize < 0) {
    return new Response("Invalid expected size", { status: 400 });
  }

  let upstream;
  try {
    upstream = await fetchAllowedSource(source, {
      headers: {
        "user-agent":
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " +
          "AppleWebKit/537.36 (KHTML, like Gecko) " +
          "Chrome/154.0.0.0 Safari/537.36",
        "referer": "https://www.canecorsopedigree.com/",
        "accept":
          "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
      },
    });
  } catch (error) {
    return Response.json(
      { status: "source_fetch_error", error: String(error) },
      { status: 502 },
    );
  }

  if (!upstream.ok) {
    return Response.json(
      { status: "source_http_error", source_status: upstream.status },
      { status: 502 },
    );
  }

  const contentType = (
    upstream.headers.get("content-type") || ""
  ).split(";", 1)[0].toLowerCase();
  if (!contentType.startsWith("image/")) {
    return Response.json(
      { status: "source_not_image", content_type: contentType },
      { status: 422 },
    );
  }

  const data = await upstream.arrayBuffer();
  if (!data.byteLength) {
    return Response.json({ status: "source_empty" }, { status: 422 });
  }
  const archivedSizeMatch =
    !expectedSize || data.byteLength === expectedSize;

  const stored = await env.MEDIA_BUCKET.put(key, data, {
    httpMetadata: { contentType },
  });

  const verified = await env.MEDIA_BUCKET.head(key);
  if (!verified || verified.size !== data.byteLength) {
    return Response.json(
      {
        status: "r2_verify_failed",
        key,
        expected_size: data.byteLength,
        actual_size: verified ? verified.size : null,
      },
      { status: 500 },
    );
  }

  if (isPhotoKey(key)) {
    await invalidateDirectPhotoRenditions(env, key);
    const warm = prewarmUploadedDogPhoto(
      env, key, verified.httpEtag || stored.httpEtag, data,
    );
    if (ctx && typeof ctx.waitUntil === "function") ctx.waitUntil(warm);
    else await warm;
  }

  return Response.json(
    {
      status: "stored",
      key,
      size: verified.size,
      etag: stored.httpEtag,
      source_status: upstream.status,
      content_type: contentType,
      r2_verified: true,
      archived_size_match: archivedSizeMatch,
      archived_expected_size: expectedSize || null,
    },
    { status: 201 },
  );
}

async function handleSignedMedia(request, env, url) {
  if (request.method !== "GET" && request.method !== "HEAD") {
    return new Response("Method not allowed", {
      status: 405,
      headers: { allow: "GET,HEAD" },
    });
  }

  const key = safeKey(url, "/_media/");
  if (!key) return new Response("Invalid key", { status: 400 });

  const expires = url.searchParams.get("expires") || "";
  const signature = url.searchParams.get("signature") || "";
  if (!/^\d+$/.test(expires)) {
    return new Response("Forbidden", { status: 403 });
  }

  const now = Math.floor(Date.now() / 1000);
  const expiry = Number(expires);
  if (expiry < now || expiry > now + 3600) {
    return new Response("Expired", { status: 403 });
  }

  const expected = await hmacHex(
    env.R2_GATEWAY_SIGNING_KEY || env.DJANGO_SECRET_KEY,
    ["GET", key, expires].join("\n"),
  );
  if (!constantTimeEqual(expected, signature)) {
    return new Response("Forbidden", { status: 403 });
  }

  // Restrict Drive fallback to previously-public, signed archive originals.
  const archived = await originalDriveArchivePhoto(key, request.method);
  if (archived) return archived;

  const object = request.method === "HEAD"
    ? await env.MEDIA_BUCKET.head(key)
    : await env.MEDIA_BUCKET.get(key);
  if (!object) return new Response("Not found", { status: 404 });

  return new Response(request.method === "HEAD" ? null : object.body, {
    status: 200,
    headers: r2Headers(object),
  });
}


const PHOTO_WIDTHS = Object.freeze({ thumb: 176, card: 480, portrait: 960 });
const PHOTO_RENDITION_VERSION = "v1";
const PHOTO_DIRECT_VERSION = "direct-v2";
const PHOTO_EDGE_TTL = 60;
const PHOTO_BROWSER_TTL = 45;

// Persist each compressed rendition against the source R2 ETag. A replacement
// under the same object key receives new variants instead of stale pixels.
// These objects live in the private R2 bucket, never on a public URL.
async function photoRenditionKey(key, etag, variant) {
  if (!etag) return null;
  const sourceId = await sha256Hex(encoder.encode(key));
  const revision = String(etag).replace(/[^a-zA-Z0-9]/g, "").slice(0, 64);
  if (!revision) return null;
  return `cca-photo-renditions/${PHOTO_RENDITION_VERSION}/${sourceId}/${revision}/${variant}.webp`;
}

// A stable private R2 key lets every subsequent profile/photo request obtain
// the finished WebP with ONE get(), rather than HEAD(original) then GET(WebP).
// It is never exposed directly: the HMAC-checked /_thumb/ route remains the
// only public path. The key is invalidated when the original is replaced.
async function photoDirectRenditionKey(key, variant) {
  return `cca-photo-renditions/${PHOTO_DIRECT_VERSION}/${await sha256Hex(encoder.encode(key))}/${variant}.webp`;
}

async function invalidateDirectPhotoRenditions(env, key) {
  if (!isPhotoKey(key)) return;
  await Promise.all(Object.keys(PHOTO_WIDTHS).map(async (variant) => {
    await env.MEDIA_BUCKET.delete(await photoDirectRenditionKey(key, variant));
  }));
}

async function storeDirectPhotoRendition(env, key, variant, bytes) {
  await env.MEDIA_BUCKET.put(await photoDirectRenditionKey(key, variant), bytes, {
    httpMetadata: { contentType: "image/webp" },
  });
}

async function optimizedPhotoBytes(env, stream, variant) {
  const rendition = (
    await env.IMAGES.input(stream)
      .transform({ width: PHOTO_WIDTHS[variant], fit: "scale-down" })
      .output({ format: "image/webp", quality: 80, anim: true })
  ).response();
  const bytes = await rendition.arrayBuffer();
  if (!bytes.byteLength) throw new Error("Empty WebP rendition");
  return bytes;
}

async function storePhotoRendition(env, key, etag, variant, bytes) {
  const renditionKey = await photoRenditionKey(key, etag, variant);
  if (!renditionKey) return;
  await env.MEDIA_BUCKET.put(renditionKey, bytes, {
    httpMetadata: { contentType: "image/webp" },
  });
}

async function prewarmUploadedDogPhoto(env, key, etag, originalBytes) {
  // Uploads return promptly; transformations are performed with waitUntil.
  // Skip documents, non-photos and unavailable Images bindings entirely.
  if (!isPhotoKey(key) || !etag ||
      !env.IMAGES || typeof env.IMAGES.input !== "function") return;
  await Promise.allSettled(Object.keys(PHOTO_WIDTHS).map(async (variant) => {
    const stream = new Response(originalBytes).body;
    const bytes = await optimizedPhotoBytes(env, stream, variant);
    await Promise.all([
      storeDirectPhotoRendition(env, key, variant, bytes),
      storePhotoRendition(env, key, etag, variant, bytes),
    ]);
  }));
}

function optimizedPhotoResponse(body, variant, cacheStatus) {
  return new Response(body, {
    status: 200,
    headers: {
      "content-type": "image/webp",
      "cache-control": `private, max-age=${PHOTO_BROWSER_TTL}`,
      "x-content-type-options": "nosniff",
      "x-cca-image-variant": variant,
      "x-cca-image-cache": cacheStatus,
    },
  });
}

function cacheOptimizedPhoto(cache, cacheKey, response, ctx) {
  if (!cache) return;
  const headers = new Headers(response.headers);
  headers.set("cache-control", `public, max-age=${PHOTO_EDGE_TTL}`);
  const put = cache.put(cacheKey, new Response(response.clone().body, {
    status: 200, headers,
  }));
  if (ctx && typeof ctx.waitUntil === "function") ctx.waitUntil(put);
  else return put;
}


// Emergency read-only fallback: only original public archive keys from the
// owner's verified Google Drive archive. It never handles private documents,
// medical evidence, new uploads, or user-created photographs. HMAC validation
// happens BEFORE calling this function.
function driveArchiveIdForKey(key) {
  if (typeof key !== "string" ||
      !/^dogs\\/archive\\/\\d{3}\\/\\d+\\.(?:jpe?g|png|webp|avif)$/.test(key)) {
    return null;
  }
  return Object.hasOwn(driveArchiveIds, key) ? driveArchiveIds[key] : null;
}

async function originalDriveArchivePhoto(key, method = "GET") {
  const id = driveArchiveIdForKey(key);
  if (!id) return null;
  if (method === "HEAD") {
    return new Response(null, {
      status: 200,
      headers: {
        "content-type": "image/jpeg",
        "cache-control": "private, max-age=30",
        "x-cca-image-source": "owner-drive-archive",
      },
    });
  }
  const url = "https://drive.google.com/uc?export=download&id=" +
    encodeURIComponent(id);
  // The owner's already-shared archive is the source of record during R2
  // downtime. The redirect does not require paid R2 or image transformations.
  return new Response(null, {
    status: 302,
    headers: {
      location: url,
      "cache-control": "private, max-age=30",
      "x-cca-image-source": "owner-drive-archive",
    },
  });
}

function isPhotoKey(key) {
  return (
    typeof key === "string" &&
    key.startsWith("dogs/") &&
    !key.split("/").includes("..") &&
    /\.(jpe?g|png|webp|avif)$/i.test(key)
  );
}

function photoSignatureMessage(key, variant, expires) {
  return ["GET", key, variant, expires].join("\n");
}

async function handleOptimizedDogPhoto(request, env, url, ctx) {
  if (request.method !== "GET" && request.method !== "HEAD") {
    return new Response("Method not allowed", {
      status: 405, headers: { allow: "GET,HEAD" },
    });
  }

  const key = safeKey(url, "/_thumb/");
  const variant = url.searchParams.get("variant") || "";
  if (!isPhotoKey(key) || !Object.hasOwn(PHOTO_WIDTHS, variant)) {
    return new Response("Not found", { status: 404 });
  }

  // A signed, short-lived URL is required *before* consulting the shared
  // rendition cache. Nothing here serves arbitrary R2 paths or evidence.
  const expires = url.searchParams.get("expires") || "";
  const signature = url.searchParams.get("signature") || "";
  const now = Math.floor(Date.now() / 1000);
  if (!/^\d+$/.test(expires) ||
      Number(expires) < now ||
      Number(expires) > now + 3600) {
    return new Response("Forbidden", { status: 403 });
  }

  const expected = await hmacHex(
    env.R2_GATEWAY_SIGNING_KEY || env.DJANGO_SECRET_KEY,
    photoSignatureMessage(key, variant, expires),
  );
  if (!constantTimeEqual(expected, signature)) {
    return new Response("Forbidden", { status: 403 });
  }

  // Serve the existing public archive directly while R2 is unavailable.
  // Every request above has already passed the signed URL validation.
  const archived = await originalDriveArchivePhoto(key, request.method);
  if (archived) return archived;

  // A HEAD request must never run an image transformation.
  if (request.method === "HEAD") {
    const source = await env.MEDIA_BUCKET.head(key);
    if (!source) return new Response(null, { status: 404 });
    return new Response(null, {
      status: 200, headers: r2Headers(source, "private, max-age=30"),
    });
  }

  const cache = globalThis.caches?.default;
  // Signed authorisation is checked before either cache lookup. The edge
  // cache is deliberately short; durable versioned R2 renditions survive
  // edge eviction and are shared across Cloudflare locations.
  const cacheKey = new Request(
    url.origin + "/__photo_cache/" + variant + "/" + encodeURIComponent(key),
  );
  if (cache) {
    const stored = await cache.match(cacheKey);
    if (stored) {
      const headers = new Headers(stored.headers);
      headers.set("cache-control", `private, max-age=${PHOTO_BROWSER_TTL}`);
      headers.set("x-cca-image-cache", "EDGE");
      return new Response(stored.body, { status: 200, headers });
    }
  }

  // Fast path: one R2 GET for the finished private preview. Avoid any
  // original-object HEAD, image transform, or sequential storage lookup.
  // This is especially important on cold browser loads in remote regions.
  const direct = await env.MEDIA_BUCKET.get(
    await photoDirectRenditionKey(key, variant),
  );
  if (direct) {
    const response = optimizedPhotoResponse(direct.body, variant, "R2-DIRECT");
    const put = cacheOptimizedPhoto(cache, cacheKey, response, ctx);
    if (put) await put;
    return response;
  }

  // Legacy images still use the verified ETag path once. Promote its
  // existing WebP to the stable private key without re-transforming it.
  const source = await env.MEDIA_BUCKET.head(key);
  if (!source) return new Response("Not found", { status: 404 });
  const renditionKey = await photoRenditionKey(
    key, source.httpEtag || source.etag, variant,
  );
  if (renditionKey) {
    const ready = await env.MEDIA_BUCKET.get(renditionKey);
    if (ready) {
      const bytes = await new Response(ready.body).arrayBuffer();
      const response = optimizedPhotoResponse(bytes, variant, "R2");
      const save = storeDirectPhotoRendition(env, key, variant, bytes).catch(() => {});
      if (ctx && typeof ctx.waitUntil === "function") ctx.waitUntil(save);
      else await save;
      const put = cacheOptimizedPhoto(cache, cacheKey, response, ctx);
      if (put) await put;
      return response;
    }
  }

  const original = await env.MEDIA_BUCKET.get(key);
  if (!original) return new Response("Not found", { status: 404 });
  if (env.IMAGES && typeof env.IMAGES.input === "function") {
    try {
      const bytes = await optimizedPhotoBytes(env, original.body, variant);
      const response = optimizedPhotoResponse(bytes, variant, "MISS");
      // Persist a WebP for future cold visitors and after short edge-cache
      // expiry. Persist failures must not delay or break this response.
      const saves = [
        storeDirectPhotoRendition(env, key, variant, bytes),
      ];
      if (renditionKey) {
        saves.push(storePhotoRendition(
          env, key, source.httpEtag || source.etag, variant, bytes,
        ));
      }
      const save = Promise.allSettled(saves);
      if (ctx && typeof ctx.waitUntil === "function") ctx.waitUntil(save);
      else await save;
      const put = cacheOptimizedPhoto(cache, cacheKey, response, ctx);
      if (put) await put;
      return response;
    } catch (error) {
      // Make fallback observable without returning raw exception details,
      // storage paths or credentials in the public response.
      const message = String(error?.message || error || "").toLowerCase();
      const reason = /quota|limit|subscription|billing|payment|credits/.test(message)
        ? "quota"
        : /unsupported|format|decode|invalid image|corrupt/.test(message)
          ? "unsupported-image"
          : /timeout|timed out/.test(message)
            ? "timeout"
            : "transform-error";
      console.warn("CCA photo conversion fallback", {
        error_name: String(error?.name || "Error").slice(0, 50),
        reason,
      });
      const fallback = await env.MEDIA_BUCKET.get(key);
      if (!fallback) return new Response("Not found", { status: 404 });
      const headers = r2Headers(fallback, "private, max-age=30");
      headers.set("x-cca-image-variant", "original-fallback");
      headers.set("x-cca-image-fallback-reason", reason);
      return new Response(fallback.body, { status: 200, headers });
    }
  }

  const headers = r2Headers(original, "private, max-age=30");
  headers.set("x-cca-image-variant", "original-fallback");
  headers.set("x-cca-image-fallback-reason", "images-binding-unavailable");
  return new Response(original.body, { status: 200, headers });
}

export { isAllowedSourceUrl, isPhotoKey, photoSignatureMessage, driveArchiveIdForKey };

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (url.pathname === "/healthz/") {
      return Response.json({ status: "ok", service: "r2-media" });
    }

    if (url.pathname.startsWith("/_r2/")) {
      return handleR2Gateway(request, env, url, ctx);
    }

    if (url.pathname.startsWith("/_r2_ingest/")) {
      return handleR2Ingest(request, env, url, ctx);
    }

    if (url.pathname.startsWith("/_media/")) {
      return handleSignedMedia(request, env, url);
    }
    if (url.pathname.startsWith("/_thumb/")) {
      return handleOptimizedDogPhoto(request, env, url, ctx);
    }

    return new Response("Not found", { status: 404 });
  },
};
