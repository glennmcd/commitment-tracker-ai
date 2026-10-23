// The format-on-edit command for .claude/cc-practices.json, which allows one formatter: this picks it by extension.
// Python goes to Ruff in backend/, and the TypeScript, JavaScript, JSON and CSS files go to Biome.
import { spawnSync } from "node:child_process";
import path from "node:path";
import { pathToFileURL } from "node:url";

const BIOME = new Set([".ts", ".tsx", ".js", ".jsx", ".mjs", ".json", ".css"]);

/** Every extension the formatter handles; .claude/cc-practices.json lists the same ones. */
export const EXTENSIONS = [".py", ...BIOME];

/** The command that formats `file`, or null for a file type that has no formatter. */
export function commandFor(file) {
  const extension = path.extname(file).toLowerCase();
  if (extension === ".py") return ["uv", "run", "--directory", "backend", "ruff", "format", file];
  // Biome skips files its config excludes (openapi.json, the generated client); that is not an error.
  if (BIOME.has(extension)) return ["bunx", "biome", "check", "--write", "--no-errors-on-unmatched", file];
  return null;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const file = process.argv[2];
  const command = file ? commandFor(file) : null;
  if (!command) process.exit(0);
  const [program, ...args] = command;
  const result = spawnSync(program, args, { stdio: "inherit" });
  process.exit(result.status ?? 1);
}
