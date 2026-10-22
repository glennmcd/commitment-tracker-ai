import { describe, expect, it } from "bun:test";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { bundleApi, bundleCommands, PYTHON_PLATFORM, PYTHON_VERSION, type Run } from "../scripts/bundle-api.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const backend = path.join(here, "../../backend");

function tempDir(): string {
  return mkdtempSync(path.join(tmpdir(), "ct-bundle-"));
}

/** Records commands; stands in for uv by creating the files a real install would. */
function fakeRun(): { calls: { command: string; args: string[]; cwd: string }[]; run: Run } {
  const calls: { command: string; args: string[]; cwd: string }[] = [];
  const run: Run = (command, args, cwd) => {
    calls.push({ command, args, cwd });
    const target = args.indexOf("--target");
    if (target >= 0) {
      const dir = args[target + 1] as string;
      mkdirSync(path.join(dir, "fastapi"), { recursive: true });
      writeFileSync(path.join(dir, "fastapi", "__init__.py"), "");
    }
  };
  return { calls, run };
}

describe("bundleCommands", () => {
  const [exportCommand, installCommand] = bundleCommands("/out/api", "/out/requirements.txt");

  it("exports the locked runtime dependencies without dev tools or the evaluation group", () => {
    expect(exportCommand?.command).toBe("uv");
    expect(exportCommand?.args).toEqual([
      "export",
      "--frozen",
      "--no-dev",
      "--no-group",
      "eval",
      "--no-editable",
      "--no-emit-project",
      "-o",
      "/out/requirements.txt",
    ]);
  });

  it("installs binary wheels for Python 3.12 on arm64 Linux into the target directory", () => {
    const args = installCommand?.args ?? [];
    expect(args.slice(0, 4)).toEqual(["pip", "install", "-r", "/out/requirements.txt"]);
    expect(args).toContain("--only-binary");
    expect(args[args.indexOf("--only-binary") + 1]).toBe(":all:");
    expect(args[args.indexOf("--target") + 1]).toBe("/out/api");
    expect(args[args.indexOf("--python-platform") + 1]).toBe("aarch64-manylinux2014");
    expect(args[args.indexOf("--python-version") + 1]).toBe("3.12");
    expect(PYTHON_PLATFORM).toBe("aarch64-manylinux2014");
    expect(PYTHON_VERSION).toBe("3.12");
  });
});

describe("bundleApi", () => {
  it("runs both uv commands from the backend directory, in order", () => {
    const dir = tempDir();
    try {
      const { calls, run } = fakeRun();
      bundleApi(path.join(dir, "api"), run);
      expect(calls.map((c) => c.args[0])).toEqual(["export", "pip"]);
      expect(calls.every((c) => path.resolve(c.cwd) === path.resolve(backend))).toBe(true);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("puts the package next to the dependencies, with prompts and the sample manifest", () => {
    const dir = tempDir();
    try {
      const out = bundleApi(path.join(dir, "api"), fakeRun().run);
      expect(existsSync(path.join(out, "fastapi", "__init__.py"))).toBe(true);
      expect(existsSync(path.join(out, "commitment_tracker", "lambda_handlers.py"))).toBe(true);
      expect(existsSync(path.join(out, "commitment_tracker", "extractor", "prompts", "v1.md"))).toBe(true);
      expect(existsSync(path.join(out, "commitment_tracker", "jobs", "samples.json"))).toBe(true);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("leaves out the evaluation harness and bytecode caches", () => {
    const dir = tempDir();
    try {
      const out = bundleApi(path.join(dir, "api"), fakeRun().run);
      const names = readdirSync(path.join(out, "commitment_tracker"), { recursive: true }).map(String);
      expect(names.some((n) => n.split(path.sep)[0] === "evaluation")).toBe(false);
      expect(names.some((n) => n.includes("__pycache__"))).toBe(false);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("starts from an empty directory", () => {
    const dir = tempDir();
    try {
      const outDir = path.join(dir, "api");
      mkdirSync(outDir, { recursive: true });
      writeFileSync(path.join(outDir, "stale.txt"), "old");
      bundleApi(outDir, fakeRun().run);
      expect(existsSync(path.join(outDir, "stale.txt"))).toBe(false);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("stops at the first failing command", () => {
    const dir = tempDir();
    try {
      const run: Run = () => {
        throw new Error("uv exited with 2");
      };
      expect(() => bundleApi(path.join(dir, "api"), run)).toThrow("uv exited with 2");
      expect(existsSync(path.join(dir, "api", "commitment_tracker"))).toBe(false);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

// The real `uv export` is offline (it reads uv.lock), so this guards the 250 MB zip limit: scikit-learn with NumPy and
// SciPy, or any dev tool, creeping back into the runtime dependencies fails here.
describe("the exported runtime dependencies", () => {
  it("hold the runtime stack and none of the evaluation or dev tools", () => {
    const dir = tempDir();
    try {
      const file = path.join(dir, "requirements.txt");
      const [exportCommand] = bundleCommands(path.join(dir, "api"), file);
      const result = Bun.spawnSync(["uv", ...(exportCommand?.args ?? [])], { cwd: backend });
      expect(result.exitCode).toBe(0);
      const names = new Set(
        readFileSync(file, "utf8")
          .split(/\r?\n/)
          .map((line) => /^([A-Za-z0-9_.-]+)==/.exec(line)?.[1]?.toLowerCase())
          .filter((name): name is string => name !== undefined),
      );
      for (const wanted of ["fastapi", "mangum", "boto3", "anthropic", "pydantic", "pydantic-settings"]) {
        expect(names.has(wanted)).toBe(true);
      }
      for (const unwanted of ["scikit-learn", "numpy", "scipy", "pytest", "ruff", "mypy"]) {
        expect(names.has(unwanted)).toBe(false);
      }
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
