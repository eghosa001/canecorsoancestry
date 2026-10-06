import assert from "node:assert/strict";
import { isAllowedSourceUrl } from "../src/r2-media.js";

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
