import { Container, getContainer } from "@cloudflare/containers";
import { env } from "cloudflare:workers";

function r2Response(body, init = {}) {
  return new Response(body, {
    ...init,
    headers: {
      "cache-control": "private, no-store",
      ...(init.headers || {}),
    },
  });
}

async function handleR2Bridge(request, workerEnv) {
  const url = new URL(request.url);
  const prefix = "/media/";
  if (!url.pathname.startsWith(prefix)) {
    return r2Response("Not found", { status: 404 });
  }

  const key = decodeURIComponent(url.pathname.slice(prefix.length));
  if (!key || key.includes("..")) {
    return r2Response("Invalid key", { status: 400 });
  }

  if (request.method === "GET") {
    const object = await workerEnv.MEDIA_BUCKET.get(key);
    if (!object) return r2Response("Not found", { status: 404 });

    const headers = new Headers();
    object.writeHttpMetadata(headers);
    headers.set("etag", object.httpEtag);
    headers.set("content-length", String(object.size));
    return new Response(object.body, { status: 200, headers });
  }

  if (request.method === "HEAD") {
    const object = await workerEnv.MEDIA_BUCKET.head(key);
    if (!object) return r2Response(null, { status: 404 });
    return r2Response(null, {
      status: 200,
      headers: {
        "content-length": String(object.size),
        "etag": object.httpEtag,
      },
    });
  }

  if (request.method === "PUT") {
    const body = await request.arrayBuffer();
    const stored = await workerEnv.MEDIA_BUCKET.put(key, body, {
      httpMetadata: {
        contentType: request.headers.get("content-type") || "application/octet-stream",
      },
    });
    return r2Response(JSON.stringify({
      status: "stored",
      key,
      etag: stored.httpEtag,
      size: body.byteLength,
    }), {
      status: 201,
      headers: { "content-type": "application/json" },
    });
  }

  if (request.method === "DELETE") {
    await workerEnv.MEDIA_BUCKET.delete(key);
    return r2Response(null, { status: 204 });
  }

  return r2Response("Method not allowed", {
    status: 405,
    headers: { allow: "GET,HEAD,PUT,DELETE" },
  });
}

export class DjangoContainer extends Container {
  defaultPort = 8080;
  sleepAfter = "10m";
  enableInternet = true;
  envVars = {
    DJANGO_SETTINGS_MODULE: "config.settings.container",
    DJANGO_SECRET_KEY: env.DJANGO_SECRET_KEY,
    DATABASE_URL: env.CONTAINER_DATABASE_URL,
    DJANGO_DB_SCHEMA: "django_app",
    DJANGO_DB_SSLMODE: "require",
    DJANGO_ALLOWED_HOSTS:
      "canecorsoancestry.com,www.canecorsoancestry.com,.workers.dev",
    DJANGO_CSRF_TRUSTED_ORIGINS:
      "https://canecorsoancestry.com,https://www.canecorsoancestry.com,https://*.workers.dev",
    SITE_URL: "https://canecorsoancestry.com",
    DJANGO_REQUIRE_OBJECT_STORAGE: "0",
    R2_BRIDGE_URL: "http://r2.internal",
  };

  static outboundByHost = {
    "r2.internal": handleR2Bridge,
  };
}

export default {
  async fetch(request, workerEnv) {
    return getContainer(workerEnv.DJANGO_CONTAINER, "app").fetch(request);
  },
};
