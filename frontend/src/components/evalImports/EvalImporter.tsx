"use client";

import { useState } from "react";
import { type ApiClient } from "@/api/client";
import type { components } from "@/api/schema";
import { checkImport, importBatch, readRequest } from "@/lib/evalImports";
import { ImportFindings } from "./ImportFindings";
import { ImportForm } from "./ImportForm";

type ImportRequest = components["schemas"]["ImportRequest"];
type ImportReport = components["schemas"]["ImportReport"];

type EvalImportState =
  | { status: "editing" }
  | { status: "checking" }
  | { status: "checked" | "importing" | "staged"; report: ImportReport };

export function EvalImporter({ client }: { client: ApiClient }) {
  // const [importState, setImportState] = useState<"editing" | "checking"|"checked" | "importing" | "staged">("editing");
  const [importState, setImportState] = useState<EvalImportState>({ status: "editing" });

  async function onImportClick() {
    if (importState.status !== "checked") return;
    setImportState({ status: "importing", report: importState.report });

    const response = await importBatch(client, {
      batch: importState.report.batch,
      source: importState.report.source,
      content: "",
      provenance: importState.report.provenance,
      today: "",
      generation_prompt: importState.report.generation_prompt,
    });
    if (response.ok) {
      setImportState({ status: "staged", report: response.job });
    } else {
      setImportState({ status: "checked", report: importState.report });
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
    setImportState({ status: "editing" });

    setImportState({ status: "checking" });
    if (!file) return;
    const read = await readRequest(file, options);
    if (!read || !read.ok || !read.job) return;

    const result = await checkImport(client, read.job);
    if (result.ok) {
      setImportState({ status: "checked", report: result.job });
    } else {
      setImportState({ status: "editing" });
    }
  }

  return (
    <div>
      <h2>Evaluation Importer</h2>
      <ImportForm onCheck={onCheckImportForm} />
      {importState.status === "checked" || importState.status === "importing" || importState.status === "staged" ? (
        <ImportFindings importReport={importState.report} />
      ) : (
        <p />
      )}
      {importState.status === "checked" && (
        <button onClick={onImportClick}>Import {importState.report.imported} items</button>
      )}
      {importState.status === "staged" && <p role="status">uv run eval review --batch {importState.report.batch}</p>}
    </div>
  );
}
