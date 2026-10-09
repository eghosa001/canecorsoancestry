import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
// This smoke-policy test is intentionally part of the Cloudflare edge deploy gate.
// It also gives us a safe no-behavior-change path to re-run edge cutover verification.
import edge, {
  cacheKey,
  edgeCacheVersion,
  hasPrivateCookie,
  isCacheablePublicPath,
  shouldWaitForOrigin,
  originRequest,
  timedOriginGet,
} from "../src/site-edge.js";

const publicUrl = new URL("https://example.test/");
const profileUrl = new URL("https://example.test/dogs/example-dog/");
assert.equal(isCacheablePublicPath(profileUrl, new Request(profileUrl)), false);
const searchUrl = new URL("https://example.test/dogs/?q=Updated+Name");
assert.equal(isCacheablePublicPath(searchUrl, new Request(searchUrl)), false);
const kennelUrl = new URL("https://example.test/kennels/example/");
assert.equal(isCacheablePublicPath(kennelUrl, new Request(kennelUrl)), false);
const pedigreeUrl = new URL("https://example.test/pedigrees/example-dog/");
assert.equal(isCacheablePublicPath(pedigreeUrl, new Request(pedigreeUrl)), false);

const csrfRequest = new Request(publicUrl, {
  headers: { cookie: "csrftoken=anonymous-token" },
});
assert.equal(hasPrivateCookie(csrfRequest), false);
assert.equal(isCacheablePublicPath(publicUrl, csrfRequest), false);
for (const path of [
  "/", "/dogs/", "/kennels/", "/statistics/", "/pedigrees/",
  "/litters/", "/dogs/suggestions/", "/sitemap.xml",
  "/sitemap-dogs.xml", "/pedigrees/virtual-mating/",
]) {
  const url = new URL(path, "https://example.test");
  assert.equal(isCacheablePublicPath(url, new Request(url)), false,
    `Approval-sensitive public route must bypass Cloudflare cache: ${path}`);
}
const staticUrl = new URL("https://example.test/static/core/site.css");
assert.equal(isCacheablePublicPath(staticUrl, new Request(staticUrl)), true);
assert.equal(isCacheablePublicPath(staticUrl, new Request(staticUrl, {
  headers: {cookie: "sessionid=member-session"}
})), false);
assert.equal(
  shouldWaitForOrigin(
    new Request(publicUrl, { headers: { accept: "text/html" } }),
    true,
  ),
  true,
);
assert.equal(
  shouldWaitForOrigin(
    new Request(publicUrl, {
      headers: {
        accept: "text/html",
        cookie: "sessionid=authenticated-session",
      },
    }),
    false,
  ),
  true,
);
assert.equal(
  shouldWaitForOrigin(
    new Request("https://example.test/dashboard/", {
      headers: {
        accept: "text/html",
        cookie: "sessionid=authenticated-session",
      },
    }),
    false,
  ),
  true,
);

const sessionRequest = new Request(publicUrl, {
  headers: { cookie: "sessionid=authenticated-session; csrftoken=token" },
});
assert.equal(hasPrivateCookie(sessionRequest), true);
assert.equal(isCacheablePublicPath(publicUrl, sessionRequest), false);

const trackedUrl = new URL(
  "https://example.test/dogs/example-dog/?source=search",
);
const trackedRequest = new Request(trackedUrl);
assert.equal(isCacheablePublicPath(trackedUrl, trackedRequest), false);

const matingUrl = new URL(
  "https://example.test/pedigrees/virtual-mating/?sire_q=Atlas&dam_q=Anthie",
);
const matingRequest = new Request(matingUrl);
assert.equal(isCacheablePublicPath(matingUrl, matingRequest), false);

const suggestionsUrl = new URL(
  "https://example.test/dogs/suggestions/?q=Anthie",
);
const suggestionsRequest = new Request(suggestionsUrl, {
  headers: { accept: "application/json" },
});
assert.equal(isCacheablePublicPath(suggestionsUrl, suggestionsRequest), false);
assert.equal(edgeCacheVersion({}), "local-dev");
assert.equal(edgeCacheVersion({ EDGE_CACHE_VERSION: "release-sha-123" }), "release-sha-123");
assert.equal(
  cacheKey(trackedRequest).url,
  "https://example.test/dogs/example-dog/?__cca_edge_v=local-dev",
);
assert.equal(
  cacheKey(trackedRequest, { EDGE_CACHE_VERSION: "release-sha-123" }).url,
  "https://example.test/dogs/example-dog/?__cca_edge_v=release-sha-123",
);

console.log("Approval-sensitive pages bypass all Cloudflare HTML caching; static assets remain cached.");

const proxied = originRequest(
  new Request("https://example.test/media/dogs/example.jpg"),
  {
    ORIGIN_URL: "https://origin.example",
    ORIGIN_EDGE_SECRET: "edge-secret-test",
  },
);
assert.equal(new URL(proxied.url).host, "origin.example");
assert.equal(proxied.headers.get("x-forwarded-host"), "example.test");
assert.equal(proxied.headers.get("x-cca-edge"), "1");
assert.equal(proxied.headers.get("x-cca-origin-secret"), "edge-secret-test");


const realFetch = globalThis.fetch;
let warmupRequest = null;
globalThis.fetch = async (url, init) => {
  warmupRequest = { url: String(url), init };
  return new Response("ok", {
    status: 200,
    headers: { "x-request-id": "edge-readiness-test" },
  });
};
try {
  await timedOriginGet(
    {
      ORIGIN_URL: "https://origin.example",
      ORIGIN_EDGE_SECRET: "edge-secret-test",
    },
    "/accounts/login/",
    1000,
    "edge-readiness-test",
    "text/html",
  );
  assert.equal(warmupRequest.url, "https://origin.example/accounts/login/");
  assert.equal(warmupRequest.init.headers["x-cca-edge"], "1");
  assert.equal(
    warmupRequest.init.headers["x-cca-origin-secret"],
    "edge-secret-test",
  );
} finally {
  globalThis.fetch = realFetch;
}


// Production Cloudflare cron must prime Django homepage/search metadata, not
// merely Django health and login, to avoid avoidable cold-cache DB round trips.
const scheduledCalls = [];
let scheduledTask;
const scheduleEnv = {
  ORIGIN_URL: "http://127.0.0.1:18080",
  ORIGIN_TRANSPORT: "private-vpc",
  ORIGIN_EDGE_SECRET: "test-secret",
  ORIGIN_VPC: {
    async fetch(url, init) {
      scheduledCalls.push({ path: new URL(url).pathname, headers: init.headers });
      return new Response("ready", {
        status: 200,
        headers: { "x-request-id": "cache-prime-test" },
      });
    },
  },
};
edge.scheduled({}, scheduleEnv, {
  waitUntil(p) { scheduledTask = p; },
});
await scheduledTask;
assert.deepEqual(
  scheduledCalls.map((call) => call.path).slice(-2),
  ["/", "/dogs/"],
  "Cloudflare cron should warm Django public home and filter metadata",
);
for (const call of scheduledCalls) {
  assert.equal(call.headers["x-forwarded-proto"], "https");
  assert.equal(call.headers["x-cca-origin-secret"], "test-secret");
}
console.log("Cloudflare cron primes Django public metadata safely");

const cloudflareWorkflow = readFileSync(
  new URL("../.github/workflows/cloudflare-site-edge.yml", import.meta.url),
  "utf8",
);
const smokeWorkflow = readFileSync(
  new URL("../.github/workflows/production-smoke.yml", import.meta.url),
  "utf8",
);
assert.match(
  cloudflareWorkflow,
  /EDGE_CACHE_VERSION: edge-\$\{\{ github\.run_id \}\}/,
  "Cloudflare cache namespace must be unique to the edge workflow run",
);
assert.ok(
  cloudflareWorkflow.includes('test "$mode" = "oracle"'),
  "Cloudflare must refuse to deploy against retired origins",
);
assert.doesNotMatch(
  cloudflareWorkflow, /Provision Northflank origin/,
  "Retired provider must not trigger public edge deploys",
);
assert.match(
  smokeWorkflow,
  /EXPECTED_EDGE_CACHE_VERSION: \$\\{\\{ github\\.event_name == 'workflow_run' && format\\('edge-\\{0\\}', github\\.event\\.workflow_run\\.id\\) \\|\\| '' \\}\\}/,
  "Production smoke must verify the exact Cloudflare cache namespace",
);
assert.ok(
  cloudflareWorkflow.includes('ORIGIN_URL = "http://127.0.0.1:18080"'),
  "Oracle private loopback address should be pinned in edge deploys",
);
console.log("release handshake workflow assertions passed");
