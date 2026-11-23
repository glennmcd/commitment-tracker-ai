"use client";

import { useReducer, useRef } from "react";
import { type ApiClient } from "@/api/client";
import type { components } from "@/api/schema";
import { checkImport, importBatch, readRequest } from "@/lib/evalImports";
import { ImportFindings } from "./ImportFindings";
import { ImportForm } from "./ImportForm";

type ImportRequest = components["schemas"]["ImportRequest"];
type ImportReport = components["schemas"]["ImportReport"];

type EvalImportState =
  | { status: "editing"; error?: string }
  | { status: "checking"; error?: string }
  | { status: "checked" | "importing" | "staged"; report: ImportReport; request: ImportRequest; error?: string };

type EvalImportAction =
  | { type: "editing"; state: EvalImportState }
  | { type: "checkStarted" }
  | { type: "checkSucceeded"; report: ImportReport; request: ImportRequest; error?: string }
  | { type: "checkFailed"; error?: string }
  | { type: "importStarted" }
  | { type: "importSucceeded"; report: ImportReport; request: ImportRequest; error?: string }
  | { type: "importFailed"; error?: string };

function stateReducer(state: EvalImportState, action: EvalImportAction): EvalImportState {
  switch (action.type) {
    case "editing":
      switch (state.status) {
        case "editing":
        case "checking":
        case "checked":
        case "importing":
        case "staged":
          return { status: "editing" } as EvalImportState;
      }
    case "checkStarted":
      return { ...state, status: "checking" } as EvalImportState;
    case "checkSucceeded":
      return {
        status: "checked",
        report: action.report,
        request: action.request,
        error: action.error,
      } as EvalImportState;
    case "checkFailed":
      return { ...state, status: "editing", error: action.error } as EvalImportState;
    case "importStarted":
      return { ...state, status: "importing" } as EvalImportState;
    case "importSucceeded":
      return {
        status: "staged",
        report: action.report,
        request: action.request,
        error: action.error,
      } as EvalImportState;
    case "importFailed":
      return { ...state, status: "checked", error: action.error } as EvalImportState;
    default:
      return state;
  }
}
export function EvalImporter({ client }: { client: ApiClient }) {
  const [importState, stateDispatch] = useReducer(stateReducer, {
    status: "editing",
  } as EvalImportState);

  const batchRef = useRef<HTMLInputElement>(null);

  async function onImportClick() {
    if (importState.status !== "checked") return;
    stateDispatch({ type: "importStarted" });

    const response = await importBatch(client, importState.request);
    if (response.ok) {
      stateDispatch({ type: "importSucceeded", report: response.job, request: importState.request, error: undefined });
    } else {
      stateDispatch({
        type: "importFailed",

        error: response?.message ?? undefined,
      });
      if (response.code === "batch_exists") batchRef.current?.focus();
    }
  }

  async function onCheckClick(
    file: File | null,
    options: {
      batch: string;
      provenance: string;
      generationPrompt: string;
    },
  ): Promise<void> {
    stateDispatch({ type: "checkStarted" });
    if (!file) {
      stateDispatch({ type: "checkFailed", error: "file is required" });
      return;
    }
    const read = await readRequest(file, options);
    if (!read || !read.ok) {
      stateDispatch({ type: "checkFailed", error: read.message ?? "Failed to read request" });
      return;
    }

    const result = await checkImport(client, read.job);
    if (result.ok) {
      stateDispatch({ type: "checkSucceeded", report: result.job, request: read.job, error: undefined });
    } else {
      stateDispatch({ type: "checkFailed", error: result.message ?? "Failed to check import" });
    }
  }

  return (
    <div>
      <h2>Evaluation Importer</h2>
      <ImportForm
        disabled={importState.status === "checking" || importState.status === "importing"}
        batchRef={batchRef}
        onCheck={onCheckClick}
        onEdit={() => stateDispatch({ type: "editing", state: { status: "editing" } })}
      />
      {"report" in importState ? <ImportFindings importReport={importState.report} /> : null}
      {importState.status === "checked" && importState.report.imported > 0 && (
        <button onClick={onImportClick}>Import {importState.report.imported} items</button>
      )}
      {importState.status === "staged" && (
        <p role="status">
          ls ./eval/sets/staging/{importState.report.batch}; git commit; uv run eval review --batch{" "}
          {importState.report.batch}
        </p>
      )}
      {importState.error && <p role="alert">{importState.error}</p>}
    </div>
  );
}
