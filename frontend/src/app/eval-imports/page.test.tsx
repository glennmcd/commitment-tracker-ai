import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiConfigError } from "@/api/client";
import { clearPassword, getPassword, passwordRejected, setPassword } from "@/lib/password";
import EvalImportsPage from "./page";

const client = { 
  GET: vi.fn((...args) => {
    debugger; // Or set a breakpoint on this line in VS Code
  }) 
};
const getApiClient = vi.fn();

vi.mock("@/api/client", async (original) => ({
  ...(await original<typeof import("@/api/client")>()),
  getApiClient: () => getApiClient(),
}));

describe("EvalImport password gate", () => {
  afterEach(() => clearPassword());

  it("Has one h1", async () => {
    setPassword("open sesame");
    render(<EvalImportsPage  />);
    const h1s = screen.getAllByRole("heading", { level: 1 });
    expect(h1s.length).toBe(1);
  });
  it("opens straight away in a EvalImportsPage", async () => {
    setPassword("open sesame");
    render(<EvalImportsPage  />);

    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
    expect(
      await screen.findByText("Importing writes to the repository, so it works only against a local API."),
    ).toBeInTheDocument();
    expect(await screen.findByText("Import evaluation items.")).toBeInTheDocument();
    expect(screen.queryByLabelText("JSONL file")).toBeInTheDocument();
  });
  it("Keeps the importer behind the password", () => {
    render(<EvalImportsPage  />);
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(screen.queryByLabelText("JSONL file")).not.toBeInTheDocument();
  });
});
