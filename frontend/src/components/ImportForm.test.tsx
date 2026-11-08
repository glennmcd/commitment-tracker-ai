import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import RenderResult from "next/dist/server/render-result";
import { beforeEach, describe, expect, it, type TestOptions, vi } from "vitest";
import { ApiConfigError } from "@/api/client";
import type { ErrorCode } from "@/lib/apiErrors";
import { job, span } from "@/test/builders";
import { ImportForm } from "./ImportForm";

describe("ImportForm", () => {
  it("renders the inputs", () => {
    const rr = render(
      <ImportForm onCheck={() => ({ file: null, outputs: { batch: "", provenance: "", generationPrompt: "" } })} />,
    );
    expect(screen.getByLabelText("JSONL file")).toBeInTheDocument();
    expect(screen.getByLabelText("Batch")).toBeInTheDocument();
    expect(screen.getByLabelText("Provenance")).toBeInTheDocument(); // expect(screen.getByRole("textbox", { name: "file" })).toBeInTheDocument();
  });

  it("displays the selected file name", async () => {
    const rr = render(
      <ImportForm onCheck={() => ({ file: null, outputs: { batch: "", provenance: "", generationPrompt: "" } })} />,
    );
    const fileInput = rr.container.querySelector('input[name="file"]') as HTMLInputElement;
    const file = new File(["file content"], "test-file.txt", { type: "text/plain" });
    await userEvent.upload(fileInput, file);
    await waitFor(() => {
      expect(rr.container).toHaveTextContent("test-file.txt");
    });
  });

  it("set batch input to text", async () => {
    const rr = render(
      <ImportForm onCheck={() => ({ file: null, outputs: { batch: "", provenance: "", generationPrompt: "" } })} />,
    );
    const batchInput = rr.container.querySelector('input[name="batch"]') as HTMLInputElement;
    const batchText = "test-batch";
    await userEvent.type(batchInput, batchText);
    await waitFor(() => {
      expect(batchInput.value).toBe(batchText);
    });
  });

  it("disables the check button when file is not selected", async () => {
    const rr = render(
      <ImportForm onCheck={() => ({ file: null, outputs: { batch: "", provenance: "", generationPrompt: "" } })} />,
    );
    const checkButton = rr.container.querySelector('button[type="submit"]') as HTMLButtonElement;
    expect(checkButton).toBeDisabled();
  });

  it("enables the check button when file is select and no option problems", async () => {
    const rr = render(
      <ImportForm onCheck={() => ({ file: null, outputs: { batch: "", provenance: "", generationPrompt: "" } })} />,
    );
    const fileInput = rr.container.querySelector('input[name="file"]') as HTMLInputElement;
    const file = new File(["file content"], "test-file.txt", { type: "text/plain" });
    await userEvent.upload(fileInput, file);
    const batchInput = rr.container.querySelector('input[name="batch"]') as HTMLInputElement;
    const batchText = "batch01";
    await userEvent.type(batchInput, batchText);
    const provenanceInput = rr.container.querySelector('input[name="provenance"]') as HTMLInputElement;
    const provenanceText = "test-provenance";
    await userEvent.type(provenanceInput, provenanceText);

    const checkButton = rr.container.querySelector('button[type="submit"]') as HTMLButtonElement;
    await waitFor(() => {
      expect(checkButton).toBeEnabled();
    });
  });
  const testOptions: TestOptions = { timeout: 500_000 };
  it("disables the check button when provenance is empty", testOptions, async () => {
    const rr = render(
      <ImportForm onCheck={() => ({ file: null, outputs: { batch: "", provenance: "", generationPrompt: "" } })} />,
    );
    const fileInput = rr.container.querySelector('input[name="file"]') as HTMLInputElement;
    const file = new File(["file content"], "test-file.txt", { type: "text/plain" });
    await userEvent.upload(fileInput, file);
    const batchInput = rr.container.querySelector('input[name="batch"]') as HTMLInputElement;
    const batchText = "batch01";
    await userEvent.type(batchInput, batchText);

    const checkButton = rr.container.querySelector('button[type="submit"]') as HTMLButtonElement;
    await waitFor(() => {
      expect(checkButton).toBeDisabled();
    });
  });

  it("bad option problems represented in gui", testOptions, async () => {
    const rr = render(
      <ImportForm onCheck={() => ({ file: null, outputs: { batch: "", provenance: "", generationPrompt: "" } })} />,
    );
    const fileInput = rr.container.querySelector('input[name="file"]') as HTMLInputElement;
    const file = new File(["file content"], "test-file.txt", { type: "text/plain" });
    await userEvent.upload(fileInput, file);
    fileInput.value = "";
    fireEvent.change(fileInput);
    const batchInput = rr.container.querySelector('input[name="batch"]') as HTMLInputElement;
    const batchText = "Bad-batch";
    await userEvent.type(batchInput, batchText);
    const provenanceInput = rr.container.querySelector('input[name="provenance"]') as HTMLInputElement;
    const provenanceText = "badprovenance";
    await userEvent.type(provenanceInput, provenanceText);

    await waitFor(() => {
      expect(rr.container.querySelector('input[name="file"]')).toHaveAttribute("aria-invalid", "true");
      expect(rr.container.querySelector('input[name="file"]')).toHaveAccessibleDescription("Missing file");
      expect(rr.container.querySelector('input[name="batch"]')).toHaveAttribute("aria-invalid", "true");
      expect(rr.container.querySelector('input[name="batch"]')).toHaveAccessibleDescription(
        "Use lower-case letters, digits and dashes.",
      );
      expect(rr.container.querySelector('input[name="provenance"]')).toHaveAttribute("aria-invalid", "true");
      expect(rr.container.querySelector('input[name="provenance"]')).toHaveAccessibleDescription(
        "use hand-written or <family>-<model>",
      );
    });
  });
  it("checks the chosen file with its options", async () => {
    const user = userEvent.setup();
    const onCheck = vi.fn();
    const file = new File(['{"id":"gem02-01"}\n'], "gemini.jsonl");
    render(<ImportForm onCheck={onCheck} />);

    await user.upload(screen.getByLabelText("JSONL file"), file);
    await user.type(screen.getByLabelText("Batch"), "gem02");
    await user.type(screen.getByLabelText("Provenance"), "gemini-3-pro");
    await user.click(screen.getByRole("button", { name: "Check" }));

    expect(onCheck).toHaveBeenCalledWith(file, { batch: "gem02", provenance: "gemini-3-pro", generationPrompt: "" });
  });
});
