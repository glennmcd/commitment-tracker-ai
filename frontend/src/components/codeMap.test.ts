import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const componentsDir = import.meta.dirname;
const codeMap = readFileSync(path.resolve(componentsDir, "../../../docs/code-map.md"), "utf8");
const components = readdirSync(componentsDir, { withFileTypes: true })
  .filter((entry) => entry.isFile() && entry.name.endsWith(".tsx") && !entry.name.endsWith(".test.tsx"))
  .map((entry) => entry.name);

describe("docs/code-map.md", () => {
  it("finds the components", () => expect(components).toContain("Playback.tsx"));

  it.each(components)("names %s", (name) => expect(codeMap).toContain(`\`${name}\``));
});
