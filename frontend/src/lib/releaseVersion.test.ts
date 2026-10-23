import { describe, expect, it } from "vitest";
import { versionFromManifest } from "./releaseVersion";

describe("versionFromManifest", () => {
  it("reads the root package's version from release-please's manifest", () => {
    expect(versionFromManifest('{ ".": "0.2.0" }')).toBe("0.2.0");
  });

  it.each([
    ["no root entry", '{ "other": "1.0.0" }'],
    ["a version that is not a string", '{ ".": 2 }'],
    ["an empty version", '{ ".": "" }'],
    ["not JSON", "not json"],
    ["an array", "[]"],
  ])("returns nothing for %s, so the build never fails over a footer", (_name, text) => {
    expect(versionFromManifest(text)).toBeUndefined();
  });
});
