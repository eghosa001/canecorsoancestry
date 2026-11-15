import assert from "node:assert/strict";
import worker, { isAllowedSourceUrl, isPhotoKey, photoSignatureMessage } from "../src/r2-media.js";

assert.equal(
  isAllowedSourceUrl(
    new URL("https://www.canecorsopedigree.com/static/images/animal/123/456.jpg"),
  ),
  true,
);
assert.equal(
  isAllowedSourceUrl(
    new URL("https://canecorsopedigree.com/static/images/animal/example.webp"),
  ),
  true,
);

for (const value of [
  "http://www.canecorsopedigree.com/static/images/animal/123.jpg",
  "https://evil.example/static/images/animal/123.jpg",
  "https://canecorsopedigree.com.evil.example/static/images/animal/123.jpg",
  "https://www.canecorsopedigree.com/private/123.jpg",
  "https://user:pass@www.canecorsopedigree.com/static/images/animal/123.jpg",
  "https://www.canecorsopedigree.com:444/static/images/animal/123.jpg",
]) {
  assert.equal(isAllowedSourceUrl(new URL(value)), false, value);
}

console.log("R2 source URL policy tests passed");

for (const key of [
  "dogs/archive/001/example.jpg", "dogs/archive/001/example.webp",
  "dogs/profile/photo.PNG",
]) {
  assert.equal(isPhotoKey(key), true, key);
}
for (const key of [
  "documents/health/secret.jpg", "submissions/private.jpg",
  "dogs/../documents/secret.jpg", "dogs/report.pdf", "dogs/test.jpg/extra",
]) {
  assert.equal(isPhotoKey(key), false, key);
}

const key = "dogs/archive/001/example.jpg";
const variant = "thumb";
const expires = String(Math.floor(Date.now() / 1000) + 180);
const signingKey = "test-r2-photo-secret";
const encoder = new TextEncoder();
const importedKey = await crypto.subtle.importKey(
  "raw", encoder.encode(signingKey), { name: "HMAC", hash: "SHA-256" },
  false, ["sign"],
);
const signed = new Uint8Array(await crypto.subtle.sign(
  "HMAC", importedKey, encoder.encode(photoSignatureMessage(key, variant, expires)),
));
const signature = [...signed].map(byte => byte.toString(16).padStart(2, "0")).join("");
let transforms = 0;
const renditions = new Map();
let sourceEtag = '"v1"';
const photoSource = (keyName) => ({
  body: new Response("original").body, size: 8, httpEtag: sourceEtag,
  writeHttpMetadata(headers) { headers.set("content-type", "image/jpeg"); },
});
const env = {
  R2_GATEWAY_SIGNING_KEY: signingKey,
  MEDIA_BUCKET: {
    async get(askedKey) {
      if (askedKey === key) return photoSource(askedKey);
      const stored = renditions.get(askedKey);
      return stored ? {
        body: new Response(stored).body, size: stored.byteLength,
        writeHttpMetadata(h) { h.set("content-type", "image/webp"); },
      } : null;
    },
    async head(askedKey) {
      assert.equal(askedKey, key);
      return { size: 8, httpEtag: sourceEtag,
        writeHttpMetadata(headers) { headers.set("content-type", "image/jpeg"); } };
    },
    async put(askedKey, bytes, opts) {
      assert.match(askedKey, /^cca-photo-renditions\/(?:v1\/[a-f0-9]{64}\/v[12]|direct-v2\/[a-f0-9]{64})\/thumb\.webp$/);
      assert.equal(opts.httpMetadata.contentType, "image/webp");
      renditions.set(askedKey, bytes);
      return { httpEtag: '"stored"' };
    },
    async delete(askedKey) {
      if (askedKey === key) return;  // Simulated source removal in the mock.
      assert.match(askedKey, /^cca-photo-renditions\/direct-v2\/[a-f0-9]{64}\/(thumb|card|portrait)\.webp$/);
      renditions.delete(askedKey);
    },
  },
  IMAGES: {
    input(stream) {
      assert.ok(stream);
      return {
        transform(opts) {
          transforms += 1;
          assert.deepEqual(opts, { width: 176, fit: "scale-down" });
          return {
            async output(opts) {
              assert.equal(opts.format, "image/webp");
              assert.equal(opts.quality, 80);
              return { response() {
                return new Response("webp-thumbnail", {
                  headers: { "content-type": "image/webp" },
                });
              } };
            },
          };
        },
      };
    },
  },
};
const imageURL = "https://media.example.workers.dev/_thumb/" + key +
  "?variant=thumb&expires=" + expires + "&signature=" + signature;
const pending = [];
const ctx = { waitUntil(promise) { pending.push(promise); } };
const ok = await worker.fetch(new Request(imageURL), env, ctx);
assert.equal(ok.status, 200);
assert.equal(ok.headers.get("content-type"), "image/webp");
assert.equal(ok.headers.get("cache-control"), "private, max-age=45");
assert.equal(ok.headers.get("x-cca-image-variant"), "thumb");
assert.equal(ok.headers.get("x-cca-image-cache"), "MISS");
assert.equal(await ok.text(), "webp-thumbnail");
assert.equal(transforms, 1);
await Promise.all(pending);
assert.equal(renditions.size, 2, "First conversion must persist both legacy and direct WebP keys");
const coldReturn = await worker.fetch(new Request(imageURL), env, {});
assert.equal(coldReturn.headers.get("x-cca-image-cache"), "R2-DIRECT");
assert.equal(await coldReturn.text(), "webp-thumbnail");
assert.equal(transforms, 1, "Second visitor must reuse direct WebP without conversion");

// The fast path may not contact the original object at all. Catch a
// regression where it silently reintroduces an extra R2 HEAD.
let directReads = 0;
const originalHead = env.MEDIA_BUCKET.head;
env.MEDIA_BUCKET.head = async () => { throw new Error("Direct preview made an unnecessary original HEAD"); };
const originalGet = env.MEDIA_BUCKET.get;
env.MEDIA_BUCKET.get = async (askedKey) => {
  if (askedKey === key) throw new Error("Direct preview downloaded the original");
  directReads++;
  return originalGet(askedKey);
};
const instant = await worker.fetch(new Request(imageURL), env, {});
assert.equal(instant.headers.get("x-cca-image-cache"), "R2-DIRECT");
assert.equal(directReads, 1, "Fast path should do a single private R2 GET");
env.MEDIA_BUCKET.head = originalHead;
env.MEDIA_BUCKET.get = originalGet;

// A signed delete must remove every stable fast preview before a source key
// may be reused; the legacy ETag versions remain private and unreachable.
const emptyHex = [...new Uint8Array(await crypto.subtle.digest("SHA-256", new Uint8Array()))]
  .map(x => x.toString(16).padStart(2, "0")).join("");
const deletedAt = String(Math.floor(Date.now() / 1000));
const deleteMac = new Uint8Array(await crypto.subtle.sign(
  "HMAC", importedKey,
  encoder.encode(["DELETE", key, deletedAt, emptyHex].join("\n")),
));
const deleteSignature = [...deleteMac].map(x => x.toString(16).padStart(2, "0")).join("");
const deleteResponse = await worker.fetch(new Request(
  "https://media.example.workers.dev/_r2/" + key,
  { method: "DELETE", headers: {
    "x-r2-timestamp": deletedAt, "x-r2-content-sha256": emptyHex,
    "x-r2-signature": deleteSignature,
  } },
), env, {});
assert.equal(deleteResponse.status, 204);
assert.equal([...renditions.keys()].filter(k => k.includes("/direct-v2/")).length, 0);
sourceEtag = '"v2"';
const replaced = await worker.fetch(new Request(imageURL), env, {});
assert.equal(replaced.headers.get("x-cca-image-cache"), "MISS");
assert.equal(transforms, 2, "Changed original must never reuse a deleted fast preview");
const bad = await worker.fetch(new Request(imageURL.replace(signature, "bad")), env, {});
assert.equal(bad.status, 403);
assert.equal(transforms, 2, "Unsigned access must never reach image transforms");
const wrongVariant = await worker.fetch(new Request(imageURL.replace("thumb", "unexpected")), env, {});
assert.equal(wrongVariant.status, 404);
const privatePdf = await worker.fetch(new Request(imageURL.replace(key, "documents/secret.pdf")), env, {});
assert.equal(privatePdf.status, 404);
const head = await worker.fetch(new Request(imageURL, { method: "HEAD" }), env, {});
assert.equal(head.status, 200);
assert.equal(transforms, 2, "HEAD never triggers transformation");

// A newly uploaded dog photo is pre-rendered once without holding up the
// upload response. No public access to the private rendition paths exists.
const uploadKey = "dogs/new-upload.jpg";
const uploadData = encoder.encode("A NEW PHOTO");
const digestBytes = new Uint8Array(await crypto.subtle.digest("SHA-256", uploadData));
const uploadDigest = [...digestBytes].map(x => x.toString(16).padStart(2, "0")).join("");
const uploadTimestamp = String(Math.floor(Date.now() / 1000));
const uploadHmac = new Uint8Array(await crypto.subtle.sign(
  "HMAC", importedKey,
  encoder.encode(["PUT", uploadKey, uploadTimestamp, uploadDigest].join("\n")),
));
const uploadSig = [...uploadHmac].map(x => x.toString(16).padStart(2, "0")).join("");
const prewarmed = new Map();
let storedSource = null;
let uploadTransformCount = 0;
const uploadedEnv = {
  R2_GATEWAY_SIGNING_KEY: signingKey,
  MEDIA_BUCKET: {
    async put(name, bytes, opts) {
      assert.equal(opts.httpMetadata.contentType,
        name === uploadKey ? "image/jpeg" : "image/webp");
      if (name === uploadKey) {
        storedSource = bytes;
        return { httpEtag: '"upload1"' };
      }
      assert.match(name, /^cca-photo-renditions\/(?:v1\/[a-f0-9]{64}\/upload1|direct-v2\/[a-f0-9]{64})\/(thumb|card|portrait)\.webp$/);
      prewarmed.set(name, bytes);
      return { httpEtag: '"preview"' };
    },
    async head(name) {
      assert.equal(name, uploadKey);
      return { size: storedSource.byteLength, httpEtag: '"upload1"' };
    },
    async delete(name) {
      assert.match(name, /^cca-photo-renditions\/direct-v2\/[a-f0-9]{64}\/(thumb|card|portrait)\.webp$/);
      prewarmed.delete(name);
    },
  },
  IMAGES: {
    input(stream) {
      assert.ok(stream);
      return {
        transform({ width, fit }) {
          assert.equal(fit, "scale-down");
          uploadTransformCount++;
          return {
            async output(opts) {
              assert.equal(opts.format, "image/webp");
              return { response() {
                return new Response("webp-" + width, {
                  headers: { "content-type": "image/webp" },
                });
              } };
            },
          };
        },
      };
    },
  },
};
const uploadTasks = [];
const upload = await worker.fetch(new Request(
  "https://media.example.workers.dev/_r2/" + uploadKey,
  {
    method: "PUT",
    headers: {
      "content-type": "image/jpeg",
      "x-r2-timestamp": uploadTimestamp,
      "x-r2-content-sha256": uploadDigest,
      "x-r2-signature": uploadSig,
    },
    body: uploadData,
  },
), uploadedEnv, { waitUntil(p) { uploadTasks.push(p); } });
assert.equal(upload.status, 201);
assert.equal((await upload.json()).r2_verified, true);
await Promise.all(uploadTasks);
assert.equal(uploadTransformCount, 3);
assert.equal(prewarmed.size, 6, "New photos must have both direct and versioned renditions ready");
assert.equal([...prewarmed.keys()].filter(k => k.includes("direct-v2")).length, 3);
console.log("New dog uploads prewarm three private versioned WebP variants");

const emptyDigest = [...new Uint8Array(await crypto.subtle.digest("SHA-256", new Uint8Array()))]
  .map(x => x.toString(16).padStart(2, "0")).join("");
const timestamp = String(Math.floor(Date.now() / 1000));
const headSigned = new Uint8Array(await crypto.subtle.sign(
  "HMAC", importedKey, encoder.encode(["HEAD", key, timestamp, emptyDigest].join("\n")),
));
const headSignature = [...headSigned].map(x => x.toString(16).padStart(2, "0")).join("");
let readCount = 0;
let headCount = 0;
const secureEnv = {
  R2_GATEWAY_SIGNING_KEY: signingKey,
  MEDIA_BUCKET: {
    async get() { readCount += 1; return {
      body: new Response("SENSITIVE-ORIGINAL-BODY").body, size: 23,
      writeHttpMetadata(h) { h.set("content-type", "image/jpeg"); },
    }; },
    async head() { headCount += 1; return {
      size: 23,
      writeHttpMetadata(h) { h.set("content-type", "image/jpeg"); },
    }; },
  },
};
const headHeaders = {
  "x-r2-timestamp": timestamp,
  "x-r2-content-sha256": emptyDigest,
  "x-r2-signature": headSignature,
};
const promoted = await worker.fetch(new Request(
  "https://media.example.workers.dev/_r2/" + key,
  { method: "GET", headers: headHeaders },
), secureEnv);
assert.equal(promoted.status, 200);
assert.equal(await promoted.text(), "", "A HEAD signature must never read object bytes");
assert.equal(headCount, 1);
assert.equal(readCount, 0, "HEAD to GET promotion must not expose the object");
const realHead = await worker.fetch(new Request(
  "https://media.example.workers.dev/_r2/" + key,
  { method: "HEAD", headers: headHeaders },
), secureEnv);
assert.equal(realHead.status, 200);
assert.equal(headCount, 2);
assert.equal(readCount, 0);
const deniedRequest = await worker.fetch(new Request(
  "https://media.example.workers.dev/_r2/" + key,
  { method: "GET", headers: {...headHeaders, "x-r2-signature": "incorrect"} },
), secureEnv);
assert.equal(deniedRequest.status, 403);
assert.equal(readCount, 0);
const getSigned = new Uint8Array(await crypto.subtle.sign(
  "HMAC", importedKey, encoder.encode(["GET", key, timestamp, emptyDigest].join("\n")),
));
const getSignature = [...getSigned].map(x => x.toString(16).padStart(2, "0")).join("");
const realGet = await worker.fetch(new Request(
  "https://media.example.workers.dev/_r2/" + key,
  { method: "GET", headers: {...headHeaders, "x-r2-signature": getSignature} },
), secureEnv);
assert.equal(realGet.status, 200);
assert.equal(await realGet.text(), "SENSITIVE-ORIGINAL-BODY");
assert.equal(readCount, 1);
console.log("Cloudflare HEAD-to-GET R2 signature compatibility tests passed");

console.log("Signed R2 dog-photo variants and privacy tests passed");
