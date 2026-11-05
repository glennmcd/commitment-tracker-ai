import { spawnSync } from "node:child_process";
import { cpSync, mkdirSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const infraRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const backendRoot = path.resolve(infraRoot, "..", "backend");

export const DEFAULT_BUNDLE_DIR = path.join(infraRoot, "dist", "api");

/** The Lambda runtime the zip targets: Python 3.12 on arm64 (docs/decisions/0004-mangum-and-zip.md). */
export const PYTHON_VERSION = "3.12";
export const PYTHON_PLATFORM = "aarch64-manylinux2014";

/** Runs a command in a directory and throws if it fails. Replaced by a fake in tests. */
export type Run = (command: string, args: string[], cwd: string) => void;

export const run: Run = (command, args, cwd) => {
  const result = spawnSync(command, args, { cwd, stdio: "inherit" });
  if (result.error) throw new Error(`could not run ${command}: ${result.error.message}`);
  if (result.status !== 0) throw new Error(`${command} ${args.join(" ")} exited with ${result.status}`);
};

/** The two uv commands of the uv Lambda guide's zip recipe, in order. */
export function bundleCommands(outDir: string, requirementsFile: string): { command: string; args: string[] }[] {
  return [
    {
      command: "uv",
      args: [
        "export",
        "--frozen",
        "--no-dev",
        "--no-group",
        "eval",
        "--no-editable",
        "--no-emit-project",
        "-o",
        requirementsFile,
      ],
    },
    {
      command: "uv",
      args: [
        "pip",
        "install",
        "-r",
        requirementsFile,
        "--target",
        outDir,
        "--python-platform",
        PYTHON_PLATFORM,
        "--python-version",
        PYTHON_VERSION,
        "--only-binary",
        ":all:",
        "--no-installer-metadata",
        "--no-compile-bytecode",
      ],
    },
  ];
}

/**
 * The evaluation harness needs scikit-learn, which is not installed on the Lambda, so only the modules the API
 * imports ship: `api/app.py` pulls in `importer`, which pulls in `sets`, `dataset` and `leaks`. None of them may
 * import scikit-learn (see test/bundle.test.ts).
 */
export const EVALUATION_MODULES_IN_PACKAGE = new Set([
  "__init__.py",
  "importer.py",
  "sets.py",
  "dataset.py",
  "leaks.py",
]);

function inPackage(source: string): boolean {
  const name = path.basename(source);
  if (name === "__pycache__") return false;
  if (path.basename(path.dirname(source)) === "evaluation") return EVALUATION_MODULES_IN_PACKAGE.has(name);
  return true;
}

/**
 * Builds the Lambda code directory: the locked runtime dependencies for Python 3.12 on arm64 plus the
 * `commitment_tracker` package. One directory serves both functions. CDK's own bundler is not used: it shells out to
 * Docker, and building here keeps the step testable on its own (see test/bundle.test.ts).
 */
export function bundleApi(outDir: string = DEFAULT_BUNDLE_DIR, runCommand: Run = run): string {
  rmSync(outDir, { recursive: true, force: true });
  mkdirSync(outDir, { recursive: true });
  const requirementsFile = path.join(path.dirname(outDir), "requirements.txt");
  for (const { command, args } of bundleCommands(outDir, requirementsFile)) {
    runCommand(command, args, backendRoot);
  }
  cpSync(path.join(backendRoot, "src", "commitment_tracker"), path.join(outDir, "commitment_tracker"), {
    recursive: true,
    filter: inPackage,
  });
  return outDir;
}

// Runs under Node (via tsx) as well as Bun, so the main-module check cannot use Bun's import.meta.main.
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  console.log(`Bundled the Lambda code to ${bundleApi()}`);
}
