"use client";

import { useReducer, useRef, useState } from "react";
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

export function EvalImporter({ client }: { client: ApiClient }) {
  // const [importState, setImportState] = useState<"editing" | "checking"|"checked" | "importing" | "staged">("editing");
  const [importState, setImportState] = useReducer((state: EvalImportState, newState: EvalImportState) => newState, {
    status: "editing",
  });

  async function onImportClick() {
    if (importState.status !== "checked") return;
    setImportState({ status: "importing", error: undefined, report: importState.report, request: importState.request });

    const response = await importBatch(client, importState.request);
    if (response.ok) {
      setImportState({ status: "staged", report: response.job, request: importState.request, error:  undefined });
    } else {
      setImportState({ status: "checked", report: importState.report, request: importState.request, error: response?.code ?? undefined });
      if (response.code === "batch_exists") batchRef.current?.focus();
    }
  }

  async function onCheckImportForm(
    file: File | null,
    options: {
      batch: string;
      provenance: string;
      generationPrompt: string;
    },
  ): Promise<void> {
    setImportState({ status: "checking" });
    if (!file) {
      setImportState({ status: "editing" });
      return;
    }
    const read = await readRequest(file, options);
    if (!read || !read.ok || !read.job) {
      setImportState({ status: "editing",error:  "Failed to read request" });
      return;
    }

    const result = await checkImport(client, read.job);
    if (result.ok) {
      setImportState({ status: "checked", report: result.job, request: read.job });
    } else {
      setImportState({ status: "editing", error: "Failed to check import"  });
    }
  }
const batchRef = useRef<HTMLInputElement>(null)
  return (
    <div>
      <h2>Evaluation Importer</h2>
      <ImportForm batchRef={batchRef} onCheck={onCheckImportForm} onEdit={() => setImportState({ status: "editing" })} />
      {"report" in importState ? <ImportFindings importReport={importState.report} /> : null}
      {importState.status === "checked" && importState.report.imported > 0 && (
        <button onClick={onImportClick}>Import {importState.report.imported} items</button>
      )}
      {importState.status === "staged" && <p role="status">uv run eval review --batch {importState.report.batch}</p>}
      {importState.error && <p role="alert">{importState.error}</p>}
    </div>
  );
}
