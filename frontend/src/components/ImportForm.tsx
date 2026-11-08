"use client";

import { useEffect, useRef, useState } from "react";
import { type ApiClient, ApiConfigError, getApiClient } from "@/api/client";
import { optionProblems } from "@/lib/evalImports";

export function ImportForm({
  onCheck,
}: {
  onCheck: (file: File | null, outputs: { batch: string; provenance: string; generationPrompt: string }) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [batch, setBatch] = useState<string>("");
  const [provenance, setProvenance] = useState<string>("");
  const [fileIssue, setFileIssue] = useState<string | null>(null);
  const [batchIssue, setBatchIssue] = useState<string | null>(null);
  const [provenanceIssue, setProvenanceIssue] = useState<string | null>(null);

  // let fileIssue: string|null = null;
  // let batchIssue: string|null = null;
  // let provenanceIssue: string|null = null;

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setFile(event.target.files?.[0] ?? null);
    setFileIssue(optionProblems({ file: event.target.files?.[0] ?? null, batch, provenance }).file ?? null);
    if (!event.target.files?.[0]) {
      setFileIssue("Missing file");
    }
    
  };

  const handleBatchChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setBatch(event.target.value);
    setBatchIssue(optionProblems({ file, batch: event.target.value, provenance }).batch ?? null);
  };
  const handleProvenanceChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setProvenance(event.target.value);
    setProvenanceIssue(optionProblems({ file, batch, provenance: event.target.value }).provenance ?? null);
  };

  const hasOptionProblems = () => {
    const problems = optionProblems({ file, batch, provenance });
    if (Object.keys(problems).length === 0) {
      return false;
    }
    return true;
  };
  return (
    <form aria-label="file import form">
      <style>
        {`
          input[aria-invalid="true"] {
            border: 2px solid #d32f2f;
            background-color: #fde8e8;
          }
        `}
      </style>

      <label htmlFor="file">JSONL file</label>
      <input
        name="file"
        id="file"
        type="file"
        onChange={handleFileChange}
        aria-describedby="file-issue"
        aria-invalid={!!fileIssue}
      />
      {file && <p>Selected file: {file.name}</p>}
      {fileIssue && <p id="file-issue">{fileIssue}</p>}
      <label htmlFor="batch">Batch</label>
      <input
        name="batch"
        id="batch"
        type="text"
        onChange={handleBatchChange}
        aria-describedby="batch-issue"
        aria-invalid={!!batchIssue}
      />
      {batch && <p>Batch: {batch}</p>}
      {batchIssue && <p id="batch-issue">{batchIssue}</p>}
      <label htmlFor="provenance">Provenance</label>
      <input
        name="provenance"
        id="provenance"
        type="text"
        onChange={handleProvenanceChange}
        aria-describedby="provenance-issue"
        aria-invalid={!!provenanceIssue}
      />
      {provenance && <p>Provenance: {provenance}</p>}
      {provenanceIssue && <p id="provenance-issue">{provenanceIssue}</p>}
      <button
        type="submit"
        disabled={!(!!file && !hasOptionProblems())}
        onClick={(e) => {
          e.preventDefault();
          onCheck(file, { batch: batch, provenance: provenance, generationPrompt: "" });
        }}
      >
        Check
      </button>
    </form>
  );
}
