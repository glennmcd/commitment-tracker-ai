import { describe, expect, it } from "bun:test";
import { readFileSync } from "node:fs";
import { commandFor, EXTENSIONS } from "./format-file.mjs";

describe("commandFor", () => {
  it("formats Python with Ruff from the backend project", () => {
    expect(commandFor("C:/repo/backend/src/a.py")).toEqual([
      "uv",
      "run",
      "--directory",
      "backend",
      "ruff",
      "format",
      "C:/repo/backend/src/a.py",
    ]);
  });

  it.each([".ts", ".tsx", ".js", ".jsx", ".mjs", ".json", ".css"])("formats %s with Biome", (extension) => {
    expect(commandFor(`/repo/frontend/x${extension}`)).toEqual([
      "bunx",
      "biome",
      "check",
      "--write",
      "--no-errors-on-unmatched",
      `/repo/frontend/x${extension}`,
    ]);
  });

  it("leaves other files alone", () => {
    expect(commandFor("/repo/README.md")).toBeNull();
    expect(commandFor("/repo/Makefile")).toBeNull();
  });

  it("is case-insensitive about extensions", () => {
    expect(commandFor("/repo/A.PY")?.[0]).toBe("uv");
  });

  it("lists exactly the extensions it handles, for .claude/cc-practices.json", () => {
    expect([...EXTENSIONS].sort()).toEqual([".css", ".js", ".json", ".jsx", ".mjs", ".py", ".ts", ".tsx"]);
  });

  it("is what .claude/cc-practices.json runs, for the same extensions", () => {
    const config = JSON.parse(readFileSync(new URL("../.claude/cc-practices.json", import.meta.url), "utf8")) as {
      languages: string[];
      format: { extensions: string[]; command: string[] };
      checks: Record<string, string>;
    };
    expect(config.format.command).toEqual(["node", "scripts/format-file.mjs", "{file}"]);
    expect([...config.format.extensions].sort()).toEqual([...EXTENSIONS].sort());
    expect(config.languages).toEqual(["python", "typescript"]);
    expect(Object.keys(config.checks)).toEqual(
      expect.arrayContaining(["lint", "format", "typecheck", "test", "lint-ts", "typecheck-ts", "test-ts"]),
    );
  });
});
