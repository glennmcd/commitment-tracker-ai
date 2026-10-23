// Builds the site with a made-up API address (the test intercepts it) and runs the Playwright test against `out/`.
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const env = { ...process.env, NEXT_PUBLIC_API_BASE_URL: "http://api.test" };

function run(command, args) {
  const result = spawnSync(command, args, { cwd: root, env, stdio: "inherit", shell: process.platform === "win32" });
  if (result.status !== 0) process.exit(result.status ?? 1);
}

run("bun", ["run", "build"]);
run("bunx", ["playwright", "test", ...process.argv.slice(2)]);
