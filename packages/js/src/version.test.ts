import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { VERSION } from "./index.js";

// The exported VERSION is a literal because Node has no reliable runtime read
// of package.json across ESM, CJS, and bundlers. That is safe only if a test
// pins it to the manifest — otherwise a release bumps package.json, ships, and
// the constant silently reports the previous version to KIFF.
describe("VERSION", () => {
  it("matches the version in package.json", () => {
    const pkg = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
    expect(VERSION).toBe(pkg.version);
  });
});
