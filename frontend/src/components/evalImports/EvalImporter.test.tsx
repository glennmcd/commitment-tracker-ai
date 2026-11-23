import { type RenderResult, render, screen, waitFor } from "@testing-library/react";
import userEvent, { type UserEvent } from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { explain } from "@/lib/apiErrors";
import { failure, fakeClient, ok } from "@/lib/testExports";
import { nothingValid, withProblems } from "@/test/evalImportFixtures";
import { EvalImporter } from "./EvalImporter";

async function fillAndCheck(rr: RenderResult, user: UserEvent) {
  const batch = "gpt03";
  const provenance = "chatgpt-5.6-luna-high";

  const fileInput = rr.container.querySelector('input[name="file"]') as HTMLInputElement;
  const file = new File(["file content"], "test-file.txt", { type: "text/plain" });
  await user.upload(fileInput, file);
  await waitFor(() => {
    expect(rr.container).toHaveTextContent("test-file.txt");
  });
  await user.type(screen.getByLabelText(/batch/i), batch);
  await user.type(screen.getByLabelText(/provenance/i), provenance);
  expect(screen.getByRole("button", { name: "Check" })).toBeEnabled();
  await user.click(screen.getByRole("button", { name: "Check" }));
}

describe("EvalImporter", () => {
  it("batch_exists on import shows the alert, keeps the report, and focuses the Batch field", async () => {
    const user = userEvent.setup();
    const { client, post } = fakeClient([ok(withProblems), failure("batch_exists", 409)]);
    const rr = render(<EvalImporter client={client} />);

    const message = explain("batch_exists", null);

    await fillAndCheck(rr, user);

    await user.click(screen.getByRole("button", { name: "Import 22 items" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(message);

    expect(await screen.findByRole("table", { name: "Rejected lines" })).toBeInTheDocument();

    expect(screen.getByLabelText(/batch/i)).toHaveFocus();
  });
  it("the import sends exactly the request the check sent.", async () => {
    const user = userEvent.setup();
    const { client, post } = fakeClient([ok(withProblems), ok(withProblems, 201)]);
    const rr = render(<EvalImporter client={client} />);

    await fillAndCheck(rr, user);

    expect(await screen.findByRole("table", { name: "Rejected lines" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Import 22 items" }));

    expect(post).toHaveBeenLastCalledWith("/eval-imports", expect.anything());
    expect(await screen.findByRole("status")).toHaveTextContent("uv run eval review --batch gpt03");
    const x = post.mock.calls as unknown[][];

    expect(x[1]?.[1]).toEqual(x[0]?.[1]);
  });
  it("checks, then imports, then says what to do next", async () => {
    const user = userEvent.setup();
    const { client, post } = fakeClient([ok(withProblems), ok(withProblems, 201)]);
    const rr = render(<EvalImporter client={client} />);

    await fillAndCheck(rr, user);

    expect(await screen.findByRole("table", { name: "Rejected lines" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Import 22 items" }));

    expect(post).toHaveBeenLastCalledWith("/eval-imports", expect.anything());
    expect(await screen.findByRole("status")).toHaveTextContent("uv run eval review --batch gpt03");
  });
  it("Import is absent until a check has returned.", async () => {
    const user = userEvent.setup();
    const { client, post } = fakeClient([new Promise(() => {}), new Promise(() => {})]);
    const rr = render(<EvalImporter client={client} />);

    expect(screen.queryByRole("button", { name: /^Import/ })).not.toBeInTheDocument();

    await fillAndCheck(rr, user);

    expect(screen.queryByRole("button", { name: /^Import/ })).not.toBeInTheDocument();
  });
  it("a check of nothingValid shows the report but no Import button", async () => {
    const user = userEvent.setup();
    const { client, post } = fakeClient([ok(nothingValid), new Promise(() => {})]);
    const rr = render(<EvalImporter client={client} />);

    expect(screen.queryByRole("button", { name: /^Import/ })).not.toBeInTheDocument();

    await fillAndCheck(rr, user);

    expect(await screen.findByRole("table", { name: "Rejected lines" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Import/ })).not.toBeInTheDocument();
  });
  it.each(["batch", "file", "provenance"])("stale check for editable fields %s", async (field) => {
    const user = userEvent.setup();
    const { client, post } = fakeClient([ok(withProblems), new Promise(() => {})]);
    const rr = render(<EvalImporter client={client} />);

    expect(screen.queryByRole("button", { name: /^Import/ })).not.toBeInTheDocument();

    await fillAndCheck(rr, user);

    expect(await screen.findByRole("table", { name: "Rejected lines" })).toBeInTheDocument();

    if (field === "batch") {
      await user.type(screen.getByLabelText(/batch/i), "new-batch");
    } else if (field === "file") {
      const fileInput = rr.container.querySelector('input[name="file"]') as HTMLInputElement;
      const file = new File(["file content"], "test-file1.txt", { type: "text/plain" });
      await user.upload(fileInput, file);
      await waitFor(() => {
        expect(rr.container).toHaveTextContent("test-file1.txt");
      });
    } else if (field === "provenance") {
      await user.type(screen.getByLabelText(/provenance/i), "new-provenance");
    }

    expect(screen.queryByRole("table", { name: "Rejected lines" })).not.toBeInTheDocument();

    expect(screen.queryByRole("button", { name: /^Import/ })).not.toBeInTheDocument();
  });
});
