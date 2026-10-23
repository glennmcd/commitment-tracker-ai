import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ConsentBox, FeedbackButtons, FeedbackProvider } from "./Feedback";

const client = { POST: vi.fn() };

vi.mock("@/api/client", async (original) => ({
  ...(await original<typeof import("@/api/client")>()),
  getApiClient: () => client,
}));

const JOB = "a".repeat(64);
const ok = (kept = false) => ({ data: { transcript_kept: kept }, response: new Response(null, { status: 200 }) });
const failure = (code: string, status: number) => ({
  error: { error: { code, message: "m", details: [] } },
  response: new Response(null, { status }),
});

beforeEach(() => client.POST.mockReset().mockResolvedValue(ok()));

function setup() {
  render(
    <FeedbackProvider jobId={JOB}>
      <ConsentBox />
      <FeedbackButtons spanIndex={0} />
      <FeedbackButtons spanIndex={1} />
    </FeedbackProvider>,
  );
  return userEvent.setup();
}

const body = (spanIndex: number, vote: string, consent: boolean) => ({
  body: { job_id: JOB, span_index: spanIndex, vote, consent },
});

describe("Feedback", () => {
  it("renders nothing outside a provider", () => {
    const { container } = render(
      <>
        <ConsentBox />
        <FeedbackButtons spanIndex={0} />
      </>,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("sends a thumbs-up without consent and shows it pressed", async () => {
    const user = setup();

    await user.click(screen.getAllByRole("button", { name: /Right/ })[0] as HTMLElement);

    expect(client.POST).toHaveBeenCalledWith("/feedback", body(0, "up", false));
    const pressed = await screen.findAllByRole("button", { pressed: true });
    expect(pressed).toHaveLength(1);
    expect(pressed[0]).toHaveTextContent("Right");
    expect(screen.getByText("Thanks, that is noted.")).toBeInTheDocument();
  });

  it("changes a vote and tracks each span on its own", async () => {
    const user = setup();
    const [up0, up1] = screen.getAllByRole("button", { name: /Right/ });
    const [down0] = screen.getAllByRole("button", { name: /Wrong/ });

    await user.click(up0 as HTMLElement);
    await user.click(up1 as HTMLElement);
    await user.click(down0 as HTMLElement);

    await waitFor(() => expect(down0).toHaveAttribute("aria-pressed", "true"));
    expect(up0).toHaveAttribute("aria-pressed", "false");
    expect(up1).toHaveAttribute("aria-pressed", "true");
    expect(client.POST).toHaveBeenLastCalledWith("/feedback", body(0, "down", false));
  });

  it("asks for the transcript to be kept only when the box is ticked", async () => {
    const user = setup();
    const box = screen.getByRole("checkbox", { name: "Keep this transcript for up to 90 days to improve the labels." });
    expect(box).not.toBeChecked();

    await user.click(box);
    await user.click(screen.getAllByRole("button", { name: /Wrong/ })[0] as HTMLElement);

    expect(client.POST).toHaveBeenLastCalledWith("/feedback", body(0, "down", true));
  });

  it("sends earlier votes again when consent changes, so withdrawing it deletes the transcript", async () => {
    const user = setup();
    const box = screen.getByRole("checkbox");
    await user.click(box);
    await user.click(screen.getAllByRole("button", { name: /Right/ })[0] as HTMLElement);
    await user.click(screen.getAllByRole("button", { name: /Wrong/ })[1] as HTMLElement);
    client.POST.mockClear();

    await user.click(box); // withdraw

    await waitFor(() => expect(client.POST).toHaveBeenCalledTimes(2));
    expect(client.POST).toHaveBeenCalledWith("/feedback", body(0, "up", false));
    expect(client.POST).toHaveBeenCalledWith("/feedback", body(1, "down", false));
  });

  it("sends nothing when consent changes before any vote", async () => {
    const user = setup();
    await user.click(screen.getByRole("checkbox"));
    expect(client.POST).not.toHaveBeenCalled();
  });

  it("says why a vote did not go through, and does not mark it", async () => {
    client.POST.mockResolvedValue(failure("job_not_found", 404));
    const user = setup();

    await user.click(screen.getAllByRole("button", { name: /Right/ })[0] as HTMLElement);

    expect(await screen.findByText(/That job has expired/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { pressed: true })).not.toBeInTheDocument();
  });
});
