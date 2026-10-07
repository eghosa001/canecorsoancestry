import assert from "node:assert/strict";
import {
  cacheKey,
  hasPrivateCookie,
  isCacheablePublicPath,
  shouldWaitForOrigin,
  originRequest,
  timedOriginGet,
} from "../src/site-edge.js";

const publicUrl = new URL("https://example.test/dogs/example-dog/");

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
assert.equal(isCacheablePublicPath(trackedUrl, trackedRequest), true);

const matingUrl = new URL(
  "https://example.test/pedigrees/virtual-mating/?sire_q=Atlas&dam_q=Anthie",
);
const matingRequest = new Request(matingUrl);
assert.equal(isCacheablePublicPath(matingUrl, matingRequest), true);

const suggestionsUrl = new URL(
  "https://example.test/dogs/suggestions/?q=Anthie",
);
const suggestionsRequest = new Request(suggestionsUrl, {
  headers: { accept: "application/json" },
});
assert.equal(isCacheablePublicPath(suggestionsUrl, suggestionsRequest), true);
assert.equal(
  cacheKey(trackedRequest).url,
  "https://example.test/dogs/example-dog/?__cca_edge_v=mobile-upload-v85",
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
