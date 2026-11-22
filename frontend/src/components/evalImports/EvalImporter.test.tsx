import userEvent from "@testing-library/user-event";
import { waitFor, render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { withProblems } from "@/test/evalImportFixtures";
import { extendedTest, fakeClient, ok } from "@/lib/testExports";
import {EvalImporter} from "./EvalImporter";

// async function fillAndCheck(user: ReturnType<typeof userEvent.setup>, { batch, provenance }: { batch: string; provenance: string }) {
//   await user.type(screen.getByLabelText(/batch/i), batch);
//   await user.type(screen.getByLabelText(/provenance/i), provenance);
//   await user.click(screen.getByRole("button", { name: "Check" }));
// }

describe('EvalImporter', () => {
  it("checks, then imports, then says what to do next", async () => {
  const user = userEvent.setup();
  const { client, post } = fakeClient([ok(withProblems), ok(withProblems, 201)]);
  const rr = render(<EvalImporter client={client} />);

  const batch="gpt03";
  const provenance="chatgpt-luna";

  const fileInput = rr.container.querySelector('input[name="file"]') as HTMLInputElement;
  const file = new File(["file content"], "test-file.txt", { type: "text/plain" });
  await userEvent.upload(fileInput, file);
  await waitFor(() => {
    expect(rr.container).toHaveTextContent("test-file.txt");
  });
  await user.type(screen.getByLabelText(/batch/i),batch);
  await user.type(screen.getByLabelText(/provenance/i),provenance);
  expect(screen.getByRole("button", { name: "Check" })).toBeEnabled()
  await user.click(screen.getByRole("button",{name:"Check"}));

  expect(await screen.findByRole("table", { name: "Rejected lines" })).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Import 22 items" }));

  expect(post).toHaveBeenLastCalledWith("/eval-imports", expect.anything());
  expect(await screen.findByRole("status")).toHaveTextContent("uv run eval review --batch gpt03");
   });
});
