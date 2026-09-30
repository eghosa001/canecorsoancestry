const encoder = new TextEncoder();

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

function r2Headers(object, cacheControl = "private, no-store") {
  const headers = new Headers();
  if (object.writeHttpMetadata) object.writeHttpMetadata(headers);
  if (object.httpEtag) headers.set("etag", object.httpEtag);
  if (typeof object.size === "number") {
    headers.set("content-length", String(object.size));
  }
  headers.set("cache-control", cacheControl);
  headers.set("x-content-type-options", "nosniff");
  return headers;
}

async function verifyGatewayRequest(request, env, key, body) {
  const timestamp = request.headers.get("x-r2-timestamp") || "";
  const digest = request.headers.get("x-r2-content-sha256") || "";
  const signature = request.headers.get("x-r2-signature") || "";

  if (!/^\d+$/.test(timestamp)) return false;
  const now = Math.floor(Date.now() / 1000);
  if (Math.abs(now - Number(timestamp)) > 300) return false;

  const actualDigest = await sha256Hex(body);
  if (!constantTimeEqual(actualDigest, digest)) return false;

  const message = [
    request.method.toUpperCase(),
    key,
    timestamp,
    digest,
  ].join("\n");
  const expected = await hmacHex(env.DJANGO_SECRET_KEY, message);
  return constantTimeEqual(expected, signature);
}

async function handleR2Gateway(request, env, url) {
  const key = safeKey(url, "/_r2/");
  if (!key) return new Response("Invalid key", { status: 400 });

  const body = request.method === "PUT"
    ? await request.arrayBuffer()
    : new ArrayBuffer(0);

  if (!(await verifyGatewayRequest(request, env, key, body))) {
    return new Response("Forbidden", { status: 403 });
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
    return Response.json(
      {
        status: "stored",
        key,
        size: body.byteLength,
        etag: stored.httpEtag,
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
    env.DJANGO_SECRET_KEY,
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

async function proxyToCloudRun(request, env, url) {
  if (!env.CLOUD_RUN_ORIGIN) {
    return new Response("Cloud Run origin is not configured.", { status: 503 });
  }

  const target = new URL(url.pathname + url.search, env.CLOUD_RUN_ORIGIN);
  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.set("x-forwarded-host", url.host);
  headers.set("x-forwarded-proto", url.protocol.replace(":", ""));
  headers.set("x-cane-edge", "cloudflare");

  return fetch(
    new Request(target.toString(), {
      method: request.method,
      headers,
      body:
        request.method === "GET" || request.method === "HEAD"
          ? undefined
          : request.body,
      redirect: "manual",
    }),
  );
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.hostname === "www.canecorsoancestry.com") {
      const target = new URL(request.url);
      target.hostname = "canecorsoancestry.com";
      return Response.redirect(target.toString(), 301);
    }

    if (url.pathname.startsWith("/_r2/")) {
      return handleR2Gateway(request, env, url);
    }

    if (url.pathname.startsWith("/_media/")) {
      return handleSignedMedia(request, env, url);
    }

    return proxyToCloudRun(request, env, url);
  },
};
