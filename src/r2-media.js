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

  const method = request.method.toUpperCase();
  const message = [
    method,
    key,
    timestamp,
    digest,
  ].join("\n");
  const expected = await hmacHex(
    env.R2_GATEWAY_SIGNING_KEY || env.DJANGO_SECRET_KEY,
    message,
  );
  if (!constantTimeEqual(expected, signature)) {
    return { ok: false, reason: "signature", method };
  }
  return { ok: true, reason: "ok", method };
}

async function handleR2Gateway(request, env, url) {
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
          "x-r2-auth-reason": verification.reason,
          "x-r2-auth-method": verification.method || request.method.toUpperCase(),
        },
      },
    );
  }

  if (request.method === "GET") {
    const object = await env.MEDIA_BUCKET.get(key);
    if (!object) return new Response("Not found", { status: 404 });
    return new Response(object.body, {
      status: 200,
      headers: r2Headers(object),
    });
  }

  if (request.method === "HEAD") {
    const object = await env.MEDIA_BUCKET.head(key);
    if (!object) return new Response(null, { status: 404 });
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
    return new Response(null, { status: 204 });
  }

  return new Response("Method not allowed", {
    status: 405,
    headers: { allow: "GET,HEAD,PUT,DELETE" },
  });
}

async function handleR2Ingest(request, env, url) {
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

  const object = request.method === "HEAD"
    ? await env.MEDIA_BUCKET.head(key)
    : await env.MEDIA_BUCKET.get(key);
  if (!object) return new Response("Not found", { status: 404 });

  return new Response(request.method === "HEAD" ? null : object.body, {
    status: 200,
    headers: r2Headers(object),
  });
}

export { isAllowedSourceUrl };

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/healthz/") {
      return Response.json({ status: "ok", service: "r2-media" });
    }

    if (url.pathname.startsWith("/_r2/")) {
      return handleR2Gateway(request, env, url);
    }

    if (url.pathname.startsWith("/_r2_ingest/")) {
      return handleR2Ingest(request, env, url);
    }

    if (url.pathname.startsWith("/_media/")) {
      return handleSignedMedia(request, env, url);
    }

    return new Response("Not found", { status: 404 });
  },
};
