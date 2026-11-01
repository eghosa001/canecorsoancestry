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
const env = {
  R2_GATEWAY_SIGNING_KEY: signingKey,
  MEDIA_BUCKET: {
    async get(askedKey) {
      assert.equal(askedKey, key);
      return { body: new Response("original").body, size: 8,
        writeHttpMetadata(headers) { headers.set("content-type", "image/jpeg"); } };
    },
    async head(askedKey) {
      assert.equal(askedKey, key);
      return { size: 8,
        writeHttpMetadata(headers) { headers.set("content-type", "image/jpeg"); } };
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
const ok = await worker.fetch(new Request(imageURL), env, {});
assert.equal(ok.status, 200);
assert.equal(ok.headers.get("content-type"), "image/webp");
assert.equal(ok.headers.get("cache-control"), "private, max-age=45");
assert.equal(ok.headers.get("x-cca-image-variant"), "thumb");
assert.equal(await ok.text(), "webp-thumbnail");
assert.equal(transforms, 1);
const bad = await worker.fetch(new Request(imageURL.replace(signature, "bad")), env, {});
assert.equal(bad.status, 403);
assert.equal(transforms, 1, "Unsigned access must never reach image transforms");
const wrongVariant = await worker.fetch(new Request(imageURL.replace("thumb", "unexpected")), env, {});
assert.equal(wrongVariant.status, 404);
const privatePdf = await worker.fetch(new Request(imageURL.replace(key, "documents/secret.pdf")), env, {});
assert.equal(privatePdf.status, 404);
const head = await worker.fetch(new Request(imageURL, { method: "HEAD" }), env, {});
assert.equal(head.status, 200);
assert.equal(transforms, 1, "HEAD never triggers transformation");

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
