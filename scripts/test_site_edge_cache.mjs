import assert from "node:assert/strict";
import {
  cacheKey,
  hasPrivateCookie,
  isCacheablePublicPath,
} from "../src/site-edge.js";

const publicUrl = new URL("https://example.test/dogs/example-dog/");

const csrfRequest = new Request(publicUrl, {
  headers: { cookie: "csrftoken=anonymous-token" },
});
assert.equal(hasPrivateCookie(csrfRequest), false);
assert.equal(isCacheablePublicPath(publicUrl, csrfRequest), true);

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
assert.equal(
  cacheKey(trackedRequest).url,
  "https://example.test/dogs/example-dog/?__cca_edge_v=brand-logo-v4",
);

console.log("site-edge cache policy tests passed");
