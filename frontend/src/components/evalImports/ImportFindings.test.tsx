import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import RenderResult from "next/dist/server/render-result";
import { beforeEach, describe, expect, it, type TestOptions, vi } from "vitest";
import { ApiConfigError } from "@/api/client";
import type { components } from "@/api/schema";
import type { ErrorCode } from "@/lib/apiErrors";
import { job, span } from "@/test/builders";
import { ImportFindings } from "./ImportFindings";

type ImportReport = components["schemas"]["ImportReport"];
type Rejection = components["schemas"]["Rejection"];
type DateDisagreement = components["schemas"]["DateDisagreement"];
type NearDuplicate = components["schemas"]["NearDuplicate"];

const getImportReport = (over: Partial<ImportReport> = {}): ImportReport => {
  return {
    batch: "batch01",
    source: "test-source",
    provenance: "test-provenance",
    imported_on: "2024-06-18",
    generation_prompt: "",
    imported: 0,
    rejections: [],
    date_disagreements: [],
    near_duplicates: [],
    ...over,
  };
};

const summary = "imported: 0 | rejected: 0 | date disagreements: 0 | near duplicates: 0";

describe("ImportFindings", () => {
  it("renders the inputs", () => {
    const rr = render(<ImportFindings importReport={getImportReport()} />);
    expect(screen.getByText("Import Findings")).toBeInTheDocument();
    expect(screen.getByText(summary)).toBeInTheDocument();
  });

  it("renders the rejected lines summary", () => {
    const rejectionList = [
      { line: 1, reason: "reason1`" },
      { line: 2, reason: "reason2" },
    ];
    const importReport = getImportReport({ rejections: rejectionList });
    const rr = render(<ImportFindings importReport={importReport} />);
    const table = screen.getByRole("table", { name: "Rejected lines" });
    const lines = within(table).getAllByRole("row");
    expect(lines).toHaveLength(rejectionList.length + 1); // +1 for the header row
    rejectionList.forEach(({ line, reason }, index) => {
      const row = lines[index + 1]; // skip header row
      if (!row) throw new Error(`Row for index ${index} not found`);
      expect(within(row).getByText(String(line))).toBeInTheDocument();
      expect(within(row).getByText(reason)).toBeInTheDocument();
    });
  });

  it("renders Dates to check table", () => {
    const dateDisagreementsList: DateDisagreement[] = [
      { item: "item01", span: 1, generator: "2024-06-18", resolver: null },
    ];
    const importReport = getImportReport({ date_disagreements: dateDisagreementsList });
    const rr = render(<ImportFindings importReport={importReport} />);
    const table = screen.getByRole("table", { name: "Dates to check" });
    const lines = within(table).getAllByRole("row");
    expect(lines).toHaveLength(dateDisagreementsList.length + 1); // +1 for the header row
    dateDisagreementsList.forEach(({ item, span, generator, resolver }, index) => {
      const row = lines[index + 1]; // skip header row
      if (!row) throw new Error(`Row for index ${index} not found`);
      expect(within(row).getByText(item)).toBeInTheDocument();
      expect(within(row).getByText(String(span))).toBeInTheDocument();
      expect(within(row).getByText(generator ?? "none")).toBeInTheDocument();
      expect(within(row).getByText(resolver ?? "none")).toBeInTheDocument();
    });
  });
  it("renders the near duplicates table", () => {
    const nearDuplicatesList: NearDuplicate[] = [{ item: "item1", of: "1", ratio: 0.9 }];
    const importReport = getImportReport({ near_duplicates: nearDuplicatesList });
    const rr = render(<ImportFindings importReport={importReport} />);
    const table = screen.getByRole("table", { name: "Near duplicates" });
    const lines = within(table).getAllByRole("row");
    expect(lines).toHaveLength(nearDuplicatesList.length + 1); // +1 for the header row
    nearDuplicatesList.forEach(({ item, of, ratio }, index) => {
      const row = lines[index + 1]; // skip header row
      if (!row) throw new Error(`Row for index ${index} not found`);
      expect(within(row).getByText(item)).toBeInTheDocument();
      expect(within(row).getByText(of)).toBeInTheDocument();
      expect(within(row).getByText(String(ratio))).toBeInTheDocument();
    });
  });
});

// it("displays the selected file name", async ()=>{
//   const rr = render(<ImportForm />);
//   const fileInput = rr.container.querySelector('input[name="file"]') as HTMLInputElement;
//   const file = new File(["file content"], "test-file.txt", { type: "text/plain" });
//   await userEvent.upload(fileInput, file);
//   await waitFor(() => {
//     expect(rr.container).toHaveTextContent("test-file.txt");
//   });
// })

// it("set batch input to text", async () => {
//   const rr = render(<ImportForm />);
//   const batchInput = rr.container.querySelector('input[name="batch"]') as HTMLInputElement;
//   const batchText = "test-batch";
//   await userEvent.type(batchInput, batchText);
//   await waitFor(() => {
//     expect(batchInput.value).toBe(batchText);
//   });
// });

// it("disables the check button when file is not selected", async () => {
//   const rr = render(<ImportForm />);
//   const checkButton = rr.container.querySelector('button[type="submit"]') as HTMLButtonElement;
//   expect(checkButton).toBeDisabled();
// });

// it("enables the check button when file is select and no option problems", async () => {
//   const rr = render(<ImportForm/>);
//   const fileInput = rr.container.querySelector('input[name="file"]') as HTMLInputElement;
//   const file = new File(["file content"], "test-file.txt", { type: "text/plain" });
//   await userEvent.upload(fileInput, file);
//   const batchInput = rr.container.querySelector('input[name="batch"]') as HTMLInputElement;
//   const batchText = "batch01";
//   await userEvent.type(batchInput, batchText);
//   const provenanceInput = rr.container.querySelector('input[name="provenance"]') as HTMLInputElement;
//   const provenanceText = "test-provenance";
//   await userEvent.type(provenanceInput, provenanceText);

//   const checkButton = rr.container.querySelector('button[type="submit"]') as HTMLButtonElement;
//   await waitFor(() => {
//     expect(checkButton).toBeEnabled();
//   });
// });
// const testOptions:TestOptions = {timeout: 500_000};
// it("disables the check button when provenance is empty",testOptions, async () => {
//   const rr = render(<ImportForm/>);
//   const fileInput = rr.container.querySelector('input[name="file"]') as HTMLInputElement;
//   const file = new File(["file content"], "test-file.txt", { type: "text/plain" });
//   await userEvent.upload(fileInput, file);
//   const batchInput = rr.container.querySelector('input[name="batch"]') as HTMLInputElement;
//   const batchText = "batch01";
//   await userEvent.type(batchInput, batchText);

//   const checkButton = rr.container.querySelector('button[type="submit"]') as HTMLButtonElement;
//   await waitFor(() => {
//     expect(checkButton).toBeDisabled();
//   });
// });

// it("bad option problems represented in gui", testOptions, async()=>{
//   const rr = render(<ImportForm/>);
//   const fileInput = rr.container.querySelector('input[name="file"]') as HTMLInputElement;
//   const file = new File(["file content"], "test-file.txt", { type: "text/plain" });
//   await userEvent.upload(fileInput, file);
//   fileInput.value = '';
//   fireEvent.change(fileInput);
//   const batchInput = rr.container.querySelector('input[name="batch"]') as HTMLInputElement;
//   const batchText = "Bad-batch";
//   await userEvent.type(batchInput, batchText);
//   const provenanceInput = rr.container.querySelector('input[name="provenance"]') as HTMLInputElement;
//   const provenanceText = "badprovenance";
//   await userEvent.type(provenanceInput, provenanceText);

//   await waitFor(() => {
//     expect(rr.container.querySelector('input[name="file"]')).toHaveAttribute("aria-invalid", "true");
//     expect(rr.container.querySelector('input[name="file"]')).toHaveAccessibleDescription("Missing file");
//     expect(rr.container.querySelector('input[name="batch"]')).toHaveAttribute("aria-invalid", "true");
//     expect(rr.container.querySelector('input[name="batch"]')).toHaveAccessibleDescription("Use lower-case letters, digits and dashes.");
//     expect(rr.container.querySelector('input[name="provenance"]')).toHaveAttribute("aria-invalid", "true");
//     expect(rr.container.querySelector('input[name="provenance"]')).toHaveAccessibleDescription("use hand-written or <family>-<model>");
//   });

// });
// it("checks the chosen file with its options", async () => {
//   const user = userEvent.setup();
//   const onCheck = vi.fn();
//   const file = new File(['{"id":"gem02-01"}\n'], "gemini.jsonl");
//   render(<ImportForm onCheck={onCheck} />);

//   await user.upload(screen.getByLabelText("JSONL file"), file);
//   await user.type(screen.getByLabelText("Batch"), "gem02");
//   await user.type(screen.getByLabelText("Provenance"), "gemini-3-pro");
//   await user.click(screen.getByRole("button", { name: "Check" }));

//   expect(onCheck).toHaveBeenCalledWith(file, { batch: "gem02", provenance: "gemini-3-pro", generationPrompt: "" });
// });
