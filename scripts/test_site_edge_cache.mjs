import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
// This smoke-policy test is intentionally part of the Cloudflare edge deploy gate.
// It also gives us a safe no-behavior-change path to re-run edge cutover verification.
import {
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
assert.equal(isCacheablePublicPath(publicUrl, csrfRequest), true);
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

console.log("site-edge cache policy tests passed");

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


const cloudflareWorkflow = readFileSync(
  new URL("../.github/workflows/cloudflare-site-edge.yml", import.meta.url),
  "utf8",
);
const smokeWorkflow = readFileSync(
  new URL("../.github/workflows/production-smoke.yml", import.meta.url),
  "utf8",
);
const northflankWorkflow = readFileSync(
  new URL("../.github/workflows/provision-northflank.yml", import.meta.url),
  "utf8",
);

assert.match(
  cloudflareWorkflow,
  /EDGE_CACHE_VERSION: edge-\$\{\{ github\.run_id \}\}/,
  "Cloudflare cache namespace must be unique to the edge workflow run",
);
assert.match(
  cloudflareWorkflow,
  /APP_RELEASE_SHA: \$\{\{ github\.event\.workflow_run\.head_sha \|\| '' \}\}/,
  "Cloudflare must retain the triggering Northflank app release identity",
);
assert.match(
  cloudflareWorkflow,
  /ref: \$\{\{ github\.event_name == 'workflow_run' && 'main' \|\| github\.sha \}\}/,
  "Post-Northflank edge deploys must use the latest Worker source from main",
);
assert.match(
  smokeWorkflow,
  /EXPECTED_EDGE_CACHE_VERSION: \$\{\{ github\.event_name == 'workflow_run' && format\('edge-\{0\}', github\.event\.workflow_run\.id\) \|\| '' \}\}/,
  "Production smoke must verify the exact Cloudflare cutover run namespace",
);
assert.match(
  northflankWorkflow,
  /GIT_COMMIT_SHA:\$git_sha/,
  "Northflank runtime must expose its exact deployed Git SHA",
);
assert.match(
  northflankWorkflow,
  /Northflank health release marker/,
  "Northflank deploy must verify its health release marker before succeeding",
);

console.log("release handshake workflow assertions passed");
