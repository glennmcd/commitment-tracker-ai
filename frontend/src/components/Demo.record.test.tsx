import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { job, span } from "@/test/builders";
import { Demo } from "./Demo";

const client = { POST: vi.fn(), GET: vi.fn() };

vi.mock("@/api/client", async (original) => ({
  ...(await original<typeof import("@/api/client")>()),
  getApiClient: () => client,
}));

// jsdom has no microphone, so the recorder is a button that hands over a clip.
vi.mock("./Recorder", () => ({
  Recorder: ({ onRecorded, disabled }: { onRecorded: (c: unknown) => void; disabled?: boolean }) => (
    <button type="button" disabled={disabled} onClick={() => onRecorded({ wav: new Uint8Array(10), durationMs: 5000 })}>
      fake record
    </button>
  ),
}));

const ok = (data: unknown, status = 200) => ({ data, response: new Response(null, { status }) });
const TICKET = {
  upload_id: "a".repeat(32),
  url: "https://bucket.example.com/",
  fields: { key: "uploads/x.wav" },
  max_bytes: 1_920_044,
  expires_in: 300,
};

const spoken = job([span({ turn_index: 1, owner: "Ana", recipient: "Ben" })], {
  transcript: [
    { speaker: "Ben", text: "Can you send the copy?", start_ms: 0, end_ms: 900 },
    { speaker: "Ana", text: "Yes. I'll send it by Friday, thanks.", start_ms: 1300, end_ms: 2800 },
  ],
});

beforeEach(() => {
  client.POST.mockReset();
  client.GET.mockReset();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(null, { status: 204 })),
  );
});

async function openRecordMode(user: ReturnType<typeof userEvent.setup>) {
  render(<Demo />);
  await waitFor(() => expect(screen.getByLabelText("Call date")).not.toHaveValue(""));
  await user.click(screen.getByRole("radio", { name: "Record" }));
}

describe("Demo in record mode", () => {
  it("needs a recording before it can start", async () => {
    const user = userEvent.setup();
    await openRecordMode(user);

    expect(screen.getByRole("button", { name: "Find commitments" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "fake record" }));
    expect(screen.getByRole("button", { name: "Find commitments" })).toBeEnabled();
  });

  it("uploads the clip, starts the job with the names, and shows the results with times", async () => {
    client.POST.mockImplementation(async (path: string) =>
      path === "/uploads" ? ok(TICKET) : ok({ ...spoken, status: "transcribing" }, 202),
    );
    client.GET.mockResolvedValue(ok(spoken));
    const user = userEvent.setup();
    await openRecordMode(user);

    await user.click(screen.getByRole("button", { name: "fake record" }));
    await user.type(screen.getByLabelText("First speaker"), "Ben");
    await user.type(screen.getByLabelText("Second speaker"), "Ana");
    await user.click(screen.getByRole("button", { name: "Find commitments" }));

    await screen.findByRole("region", { name: "Commitments" });
    expect(client.POST).toHaveBeenCalledWith("/uploads");
    expect(client.POST).toHaveBeenCalledWith("/jobs", {
      body: {
        upload_id: TICKET.upload_id,
        call_date: (screen.getByLabelText("Call date") as HTMLInputElement).value,
        speaker_names: ["Ben", "Ana"],
      },
    });
    expect(fetch).toHaveBeenCalledOnce();
    expect(screen.getByText("0:01")).toBeInTheDocument(); // the second turn starts at 1.3 s
  });

  it("sends no names when none are given", async () => {
    client.POST.mockImplementation(async (path: string) =>
      path === "/uploads" ? ok(TICKET) : ok({ ...spoken, status: "transcribing" }, 202),
    );
    client.GET.mockResolvedValue(ok(spoken));
    const user = userEvent.setup();
    await openRecordMode(user);

    await user.click(screen.getByRole("button", { name: "fake record" }));
    await user.click(screen.getByRole("button", { name: "Find commitments" }));

    await screen.findByRole("region", { name: "Commitments" });
    expect(client.POST).toHaveBeenCalledWith("/jobs", { body: expect.objectContaining({ speaker_names: [] }) });
  });

  it("lets the visitor swap the two speakers' names after the results arrive", async () => {
    client.POST.mockImplementation(async (path: string) =>
      path === "/uploads" ? ok(TICKET) : ok({ ...spoken, status: "transcribing" }, 202),
    );
    client.GET.mockResolvedValue(ok(spoken));
    const user = userEvent.setup();
    await openRecordMode(user);
    await user.click(screen.getByRole("button", { name: "fake record" }));
    await user.click(screen.getByRole("button", { name: "Find commitments" }));
    const ledger = await screen.findByRole("region", { name: "Commitments" });
    expect(within(ledger).getByText("Ana")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Swap the two speakers/ }));

    expect(within(screen.getByRole("region", { name: "Commitments" })).getByText("Ben")).toBeInTheDocument();
    expect(client.POST).toHaveBeenCalledTimes(2); // a relabel, not a new job
  });

  it("explains a refused upload and lets the visitor try again", async () => {
    client.POST.mockResolvedValue({
      error: { error: { code: "rate_limited", message: "m", details: [] } },
      response: new Response(null, { status: 429, headers: { "retry-after": "30" } }),
    });
    const user = userEvent.setup();
    await openRecordMode(user);

    await user.click(screen.getByRole("button", { name: "fake record" }));
    await user.click(screen.getByRole("button", { name: "Find commitments" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Too many requests. Try again in 30 seconds.");
    expect(screen.getByRole("button", { name: "Find commitments" })).toBeEnabled();
  });

  it("keeps the typed text when switching modes", async () => {
    const user = userEvent.setup();
    render(<Demo />);
    await user.type(screen.getByLabelText("Conversation"), "Ana: hi");

    await user.click(screen.getByRole("radio", { name: "Record" }));
    await user.click(screen.getByRole("radio", { name: "Type or paste" }));

    expect(screen.getByLabelText("Conversation")).toHaveValue("Ana: hi");
  });
});
