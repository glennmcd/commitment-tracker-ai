"use client";

import { type ReactNode, useEffect, useRef, useState } from "react";
import { type ApiClient, ApiConfigError, getApiClient } from "@/api/client";
import type { components } from "@/api/schema";
import { importSummary } from "@/lib/evalImports";

export type ImportReport = components["schemas"]["ImportReport"];
type Rejection = components["schemas"]["Rejection"];
type DateDisagreement = components["schemas"]["DateDisagreement"];
type NearDuplicate = components["schemas"]["NearDuplicate"];

function RejectedTable({ rejections }: { rejections: Rejection[] }) {
  if (!rejections || rejections.length === 0) return <div>No Rejections</div>;
  const sortedRows = rejections.sort((a, b) => a.line - b.line);
  const captionTable = (
    <CaptionTable
      caption="Rejected lines"
      headers={["Line", "Reason"]}
      rows={rejections.map(({ line, reason }) => [line, reason])}
    />
  );
  return captionTable;
}

function DateDisagreementTable({ rejections: dateDisagreements }: { rejections: DateDisagreement[] }) {
  if (!dateDisagreements || dateDisagreements.length === 0) return <div>No Date Disagreements</div>;
  const captionTable = (
    <CaptionTable
      caption="Dates to check"
      headers={["Item", "Span", "Generator", "Resolver"]}
      rows={dateDisagreements.map(({ item, span, generator, resolver }) => [
        item,
        span,
        generator ?? "none",
        resolver ?? "none",
      ])}
    />
  );
  return captionTable;
}

function NearDuplicateTable({ nearDuplicates }: { nearDuplicates: NearDuplicate[] }) {
  if (!nearDuplicates || nearDuplicates.length === 0) return <div>No Near Duplicates</div>;
  const captionTable = (
    <CaptionTable
      caption="Near duplicates"
      headers={["Item", "Similar to", "Similarity"]}
      rows={nearDuplicates.map(({ item, of, ratio }) => [item, of, ratio])}
    />
  );
  return captionTable;
}

function CaptionTable({ caption, headers, rows }: { caption: string; headers: string[]; rows: ReactNode[][] }) {
  return (
    <div className="table-scroll">
      <table className="data-table">
        <caption>{caption}</caption>
        <thead>
          <tr>
            {headers.map((header, index) => (
              <th key={index} scope="col">
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => (
                <td key={cellIndex}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ImportFindings({ importReport }: { importReport: ImportReport }) {
  return (
    <div>
      <h2>Import Findings</h2>
      <pre>{importSummary(importReport)}</pre>
      <RejectedTable rejections={importReport.rejections || []} />
      <DateDisagreementTable rejections={importReport.date_disagreements || []} />
      <NearDuplicateTable nearDuplicates={importReport.near_duplicates || []} />
    </div>
  );
}
