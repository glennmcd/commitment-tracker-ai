import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { job, span } from "@/test/builders";
import { Demo } from "./Demo";

const client = { POST: vi.fn(), GET: vi.fn() };

vi.mock("@/api/client", async (original) => ({
  ...(await original<typeof import("@/api/client")>()),
  getApiClient: () => client,
}));

const ok = (data: unknown, status = 200) => ({ data, response: new Response(null, { status }) });
const SAMPLES = [
  { id: "onboarding-paperwork", title: "Onboarding paperwork", duration_ms: 35_400 },
  { id: "security-review", title: "Security review", duration_ms: 31_000 },
];
const finished = job([span({ turn_index: 1 })]);

beforeEach(() => {
  client.POST.mockReset().mockResolvedValue(ok({ ...finished, status: "transcribing" }, 202));
  client.GET.mockReset().mockImplementation(async (path: string) => (path === "/samples" ? ok(SAMPLES) : ok(finished)));
});

async function openSamples(user: ReturnType<typeof userEvent.setup>) {
  render(<Demo />);
  await waitFor(() => expect(screen.getByLabelText("Call date")).not.toHaveValue(""));
  await user.click(screen.getByRole("radio", { name: "Sample call" }));
}

describe("Demo in sample mode", () => {
  it("loads the clips once the mode is chosen, not before", async () => {
    const user = userEvent.setup();
    render(<Demo />);
    expect(client.GET).not.toHaveBeenCalled();

    await user.click(screen.getByRole("radio", { name: "Sample call" }));

    expect(await screen.findByRole("radio", { name: /Onboarding paperwork/ })).toBeInTheDocument();
    expect(client.GET).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("radio", { name: "Type or paste" }));
    await user.click(screen.getByRole("radio", { name: "Sample call" }));
    expect(client.GET).toHaveBeenCalledTimes(1);
  });

  it("cannot start until a clip is picked", async () => {
    const user = userEvent.setup();
    await openSamples(user);
    await screen.findByRole("radio", { name: /Security review/ });

    expect(screen.getByRole("button", { name: "Find commitments" })).toBeDisabled();
    await user.click(screen.getByRole("radio", { name: /Security review/ }));
    expect(screen.getByRole("button", { name: "Find commitments" })).toBeEnabled();
  });

  it("starts the job from the clip id and shows the results", async () => {
    const user = userEvent.setup();
    await openSamples(user);
    await user.click(await screen.findByRole("radio", { name: /Security review/ }));
    await user.type(screen.getByLabelText("First speaker"), "Mei");

    await user.click(screen.getByRole("button", { name: "Find commitments" }));

    await screen.findByRole("region", { name: "Commitments" });
    expect(client.POST).toHaveBeenCalledWith("/jobs", {
      body: {
        sample_id: "security-review",
        call_date: (screen.getByLabelText("Call date") as HTMLInputElement).value,
        speaker_names: ["Mei"],
      },
    });
  });

  it("says so when the list cannot be loaded", async () => {
    client.GET.mockResolvedValue({
      error: { error: { code: "jobs_unavailable", message: "m", details: [] } },
      response: new Response(null, { status: 503 }),
    });
    const user = userEvent.setup();
    await openSamples(user);

    expect(await screen.findByRole("alert")).toHaveTextContent("The demo is not available right now.");
  });
});
