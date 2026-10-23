import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiConfigError } from "@/api/client";
import { clearPassword, getPassword, passwordRejected, setPassword } from "@/lib/password";
import { PasswordGate } from "./PasswordGate";

const client = { GET: vi.fn() };
const getApiClient = vi.fn();

vi.mock("@/api/client", async (original) => ({
  ...(await original<typeof import("@/api/client")>()),
  getApiClient: () => getApiClient(),
}));

const answer = (status: number) => ({ response: new Response(null, { status }) });

beforeEach(() => {
  client.GET.mockReset();
  getApiClient.mockReset().mockReturnValue(client);
});
afterEach(() => clearPassword());

function renderGate() {
  return render(
    <PasswordGate>
      <p>the demo</p>
    </PasswordGate>,
  );
}

async function enter(user: ReturnType<typeof userEvent.setup>, value: string) {
  await user.type(await screen.findByLabelText("Password"), value);
  await user.click(screen.getByRole("button", { name: "Unlock" }));
}

describe("PasswordGate", () => {
  it("hides the demo and asks for the password", async () => {
    renderGate();

    expect(await screen.findByLabelText("Password")).toHaveAttribute("type", "password");
    expect(screen.queryByText("the demo")).not.toBeInTheDocument();
    expect(client.GET).not.toHaveBeenCalled();
  });

  it("opens when the API accepts the password, and remembers it for the tab", async () => {
    client.GET.mockImplementation(async () => {
      // The password is stored before the check, so the client sends it.
      expect(getPassword()).toBe("open sesame");
      return answer(200);
    });
    const user = userEvent.setup();
    renderGate();

    await enter(user, "open sesame");

    expect(await screen.findByText("the demo")).toBeInTheDocument();
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
    expect(client.GET).toHaveBeenCalledWith("/samples");
    expect(getPassword()).toBe("open sesame");
  });

  it.each([401, 403])("stays shut and forgets a password the API refuses with %i", async (status) => {
    client.GET.mockResolvedValue(answer(status));
    const user = userEvent.setup();
    renderGate();

    await enter(user, "wrong");

    expect(await screen.findByRole("alert")).toHaveTextContent("That password is not right.");
    expect(screen.queryByText("the demo")).not.toBeInTheDocument();
    expect(getPassword()).toBeNull();
  });

  it("does not call a password wrong when the API is the problem", async () => {
    client.GET.mockResolvedValue(answer(500));
    const user = userEvent.setup();
    renderGate();

    await enter(user, "open sesame");

    expect(await screen.findByRole("alert")).toHaveTextContent("The API could not check the password");
    expect(getPassword()).toBeNull();
  });

  it("says so when the API cannot be reached", async () => {
    client.GET.mockRejectedValue(new TypeError("Failed to fetch"));
    const user = userEvent.setup();
    renderGate();

    await enter(user, "open sesame");

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach the API");
    expect(getPassword()).toBeNull();
  });

  it("says when the site has no API address", async () => {
    getApiClient.mockImplementation(() => {
      throw new ApiConfigError("NEXT_PUBLIC_API_BASE_URL is not set, so the site does not know where the API is.");
    });
    const user = userEvent.setup();
    renderGate();

    await enter(user, "open sesame");

    expect(await screen.findByRole("alert")).toHaveTextContent("NEXT_PUBLIC_API_BASE_URL");
    expect(getPassword()).toBeNull();
  });

  it("asks for something before it calls anything", async () => {
    const user = userEvent.setup();
    renderGate();

    await user.click(await screen.findByRole("button", { name: "Unlock" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Enter the password.");
    expect(client.GET).not.toHaveBeenCalled();
  });

  it("refuses a password the Authorization header cannot carry, without calling the API", async () => {
    const user = userEvent.setup();
    renderGate();

    await enter(user, "pässwörd€");

    expect(await screen.findByRole("alert")).toHaveTextContent("That password is not right.");
    expect(client.GET).not.toHaveBeenCalled();
  });

  it("opens straight away in a tab that already has the password", async () => {
    setPassword("open sesame");
    renderGate();

    expect(await screen.findByText("the demo")).toBeInTheDocument();
    expect(client.GET).not.toHaveBeenCalled();
  });

  it("closes again, with a notice, when the API later refuses the password", async () => {
    setPassword("open sesame");
    renderGate();
    await screen.findByText("the demo");

    act(() => passwordRejected());

    await waitFor(() => expect(screen.queryByText("the demo")).not.toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent("The password was not accepted. Enter it again.");
    expect(screen.getByLabelText("Password")).toHaveValue("");
  });
});
