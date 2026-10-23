import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiConfigError } from "@/api/client";
import { job, span } from "@/test/builders";
import { Demo } from "./Demo";

const client = { POST: vi.fn(), GET: vi.fn() };
const getApiClient = vi.fn();

vi.mock("@/api/client", async (original) => ({
  ...(await original<typeof import("@/api/client")>()),
  getApiClient: () => getApiClient(),
}));

const ok = (data: unknown, status = 200) => ({ data, response: new Response(null, { status }) });
const failure = (code: string, status: number) => ({
  error: { error: { code, message: "m", details: [] } },
  response: new Response(null, { status }),
});

const CONVERSATION = "Ben: Can you send the copy?\nAna: Yes. I'll send it by Friday, thanks.";

beforeEach(() => {
  client.POST.mockReset();
  client.GET.mockReset();
  getApiClient.mockReset().mockReturnValue(client);
});

async function fill(user: ReturnType<typeof userEvent.setup>, text = CONVERSATION) {
  await user.type(screen.getByLabelText("Conversation"), text.replaceAll("\n", "{Enter}"));
}

describe("Demo", () => {
  it("sends the turns and the call date, then shows the results", async () => {
    client.POST.mockResolvedValue(ok(job([], { status: "uploaded", analysis: null }), 202));
    client.GET.mockResolvedValue(ok(job([span({ turn_index: 1 })])));
    const user = userEvent.setup();
    render(<Demo />);
    await waitFor(() => expect(screen.getByLabelText("Call date")).not.toHaveValue(""));

    await fill(user);
    await user.click(screen.getByRole("button", { name: "Find commitments" }));

    const ledger = await screen.findByRole("region", { name: "Commitments" });
    expect(within(ledger).getByText("send the countersigned copy")).toBeInTheDocument();
    expect(client.POST).toHaveBeenCalledWith("/jobs", {
      body: {
        transcript: [
          { speaker: "Ben", text: "Can you send the copy?" },
          { speaker: "Ana", text: "Yes. I'll send it by Friday, thanks." },
        ],
        call_date: (screen.getByLabelText("Call date") as HTMLInputElement).value,
      },
    });
    expect(screen.getByRole("status", { name: "Progress" })).toHaveTextContent("Done.");
  });

  it("defaults the call date to today", async () => {
    render(<Demo />);
    const input = screen.getByLabelText("Call date") as HTMLInputElement;
    await waitFor(() => expect(input.value).toMatch(/^\d{4}-\d{2}-\d{2}$/));
    const now = new Date();
    expect(Number(input.value.slice(0, 4))).toBe(now.getFullYear());
  });

  it("asks for a speaker on a line without one, and calls nothing", async () => {
    const user = userEvent.setup();
    render(<Demo />);
    await waitFor(() => expect(screen.getByLabelText("Call date")).not.toHaveValue(""));

    await fill(user, "just words");
    await user.click(screen.getByRole("button", { name: "Find commitments" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Line 1 needs a speaker");
    expect(client.POST).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Conversation")).toHaveAttribute("aria-invalid", "true");
  });

  it("explains an API refusal in words", async () => {
    client.POST.mockResolvedValue(failure("daily_budget_exhausted", 503));
    const user = userEvent.setup();
    render(<Demo />);
    await waitFor(() => expect(screen.getByLabelText("Call date")).not.toHaveValue(""));

    await fill(user);
    await user.click(screen.getByRole("button", { name: "Find commitments" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The demo has reached its daily limit");
    expect(screen.getByRole("button", { name: "Find commitments" })).toBeEnabled();
  });

  it("reports a job that failed", async () => {
    client.POST.mockResolvedValue(ok(job([], { status: "uploaded", analysis: null }), 202));
    client.GET.mockResolvedValue(ok(job([], { status: "failed", error_code: "model_unavailable", analysis: null })));
    const user = userEvent.setup();
    render(<Demo />);
    await waitFor(() => expect(screen.getByLabelText("Call date")).not.toHaveValue(""));

    await fill(user);
    await user.click(screen.getByRole("button", { name: "Find commitments" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The model is unavailable right now");
    expect(screen.queryByRole("region", { name: "Commitments" })).not.toBeInTheDocument();
  });

  it("says when the site has no API address", async () => {
    getApiClient.mockImplementation(() => {
      throw new ApiConfigError("NEXT_PUBLIC_API_BASE_URL is not set, so the site does not know where the API is.");
    });
    const user = userEvent.setup();
    render(<Demo />);
    await waitFor(() => expect(screen.getByLabelText("Call date")).not.toHaveValue(""));

    await fill(user);
    await user.click(screen.getByRole("button", { name: "Find commitments" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("NEXT_PUBLIC_API_BASE_URL");
  });

  it("locks the form while a job runs", async () => {
    let release: (value: unknown) => void = () => {};
    client.POST.mockReturnValue(new Promise((resolve) => (release = resolve)));
    const user = userEvent.setup();
    render(<Demo />);
    await waitFor(() => expect(screen.getByLabelText("Call date")).not.toHaveValue(""));

    await fill(user);
    await user.click(screen.getByRole("button", { name: "Find commitments" }));

    expect(screen.getByRole("button", { name: "Working…" })).toBeDisabled();
    expect(screen.getByLabelText("Conversation")).toBeDisabled();
    expect(screen.getByRole("status", { name: "Progress" })).toHaveTextContent("Sending…");
    release(failure("rate_limited", 429));
    await screen.findByRole("alert");
  });

  it("fills the conversation from a prompt chip, which can then be sent", async () => {
    client.POST.mockResolvedValue(ok(job([], { status: "uploaded", analysis: null }), 202));
    client.GET.mockResolvedValue(ok(job([span({ turn_index: 1 })])));
    const user = userEvent.setup();
    render(<Demo />);
    await waitFor(() => expect(screen.getByLabelText("Call date")).not.toHaveValue(""));

    await user.click(screen.getByRole("button", { name: "Try a hedge" }));

    expect((screen.getByLabelText("Conversation") as HTMLTextAreaElement).value).toContain("no promises");
    await user.click(screen.getByRole("button", { name: "Find commitments" }));
    await screen.findByRole("region", { name: "Commitments" });
    expect(client.POST).toHaveBeenCalledWith("/jobs", {
      body: expect.objectContaining({
        transcript: expect.arrayContaining([expect.objectContaining({ speaker: "Ben" })]),
      }),
    });
  });

  it("offers the chips only in text mode", async () => {
    const user = userEvent.setup();
    render(<Demo />);
    expect(screen.getByRole("group", { name: "Try to trick it" })).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "Record" }));

    expect(screen.queryByRole("group", { name: "Try to trick it" })).not.toBeInTheDocument();
  });
});
