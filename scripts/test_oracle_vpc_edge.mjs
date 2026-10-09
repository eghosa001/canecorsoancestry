import assert from "node:assert/strict";
import edge, { originRequest, transportFetch, timedOriginGet } from "../src/site-edge.js";

const request = new Request("https://canecorsoancestry-oracle-candidate.example/pedigrees/");
const forwarded = originRequest(request, {
  ORIGIN_URL: "http://127.0.0.1:18080",
  CANDIDATE_FORWARD_HOST: "canecorsoancestry-site-edge.aighewieghosa111.workers.dev",
  ORIGIN_EDGE_SECRET: "test-secret",
});
assert.equal(forwarded.headers.get("x-forwarded-host"),
  "canecorsoancestry-site-edge.aighewieghosa111.workers.dev");

const calls = [];
const env = {
  ORIGIN_URL: "http://127.0.0.1:18080",
  ORIGIN_TRANSPORT: "private-vpc",
  ORIGIN_EDGE_SECRET: "test-secret",
  ORIGIN_VPC: {
    async fetch(url, init) {
      calls.push({ url: url instanceof Request ? url.url : String(url), init });
      return new Response("ready", { status: 200, headers: { "x-request-id": "ok" } });
    },
  },
};

await transportFetch(forwarded, env);
assert.equal(calls[0].url, "http://127.0.0.1:18080/pedigrees/");
await timedOriginGet(env, "/healthz/", 3000, "oracle-probe", "application/json");
assert.equal(calls[1].url, "http://127.0.0.1:18080/healthz/");
assert.equal(calls[1].init.headers["x-forwarded-proto"], "https",
  "Readiness requests must not be redirected by Django SECURE_SSL_REDIRECT");
assert.equal(calls[1].init.headers["x-cca-origin-secret"], "test-secret",
  "Readiness requests must retain trusted edge authentication");
await timedOriginGet(env, "/accounts/login/", 4500, "auth-readiness-check", "text/html");
assert.equal(calls[2].init.headers["x-forwarded-proto"], "https",
  "The auth endpoint must see HTTPS through the private VPC");
assert.equal(calls[2].url, "http://127.0.0.1:18080/accounts/login/");

await assert.rejects(() => transportFetch(forwarded, {
  ORIGIN_TRANSPORT: "private-vpc",
}), /not configured/);

const guarded = await edge.fetch(request, {
  CANDIDATE_GUARD_KEY: "secret",
}, {});
assert.equal(guarded.status, 404);
assert.equal(guarded.headers.get("cache-control"), "no-store");
assert.equal(guarded.headers.get("x-robots-tag"), "noindex, nofollow");

console.log("Oracle VPC transport and private candidate gate passed");
