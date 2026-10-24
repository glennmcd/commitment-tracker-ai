/**
 * Reads the exported evaluation data at build time (server components and generateStaticParams only). The site is a
 * static export, so these run once in `next build`; the browser never fetches the files.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import indexJson from "@/data/evals/index.json";
import { type EvalIndex, type EvalRun, parseIndex, parseRun } from "@/lib/evals";

const RUNS_DIR = path.join(process.cwd(), "src", "data", "evals", "runs");
const RUN_ID = /^[\w.-]+$/;

export function loadIndex(): EvalIndex {
  return parseIndex(indexJson);
}

export function runIds(): string[] {
  return loadIndex().runs.map((row) => row.run);
}

export function loadRun(id: string): EvalRun {
  if (!RUN_ID.test(id) || !runIds().includes(id)) throw new Error(`unknown evaluation run ${id}`);
  return parseRun(JSON.parse(readFileSync(path.join(RUNS_DIR, `${id}.json`), "utf8")));
}
