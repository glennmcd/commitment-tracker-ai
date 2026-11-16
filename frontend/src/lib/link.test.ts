import { afterEach, describe, expect, it, vi } from "vitest";
import { clearSource, getSource, setSource, takeLinkParams } from "./link";

const START = window.location.href;

function visit(search: string): void {
  window.history.replaceState(null, "", `/demo${search}#results`);
}

afterEach(() => {
  vi.restoreAllMocks();
  clearSource();
  window.history.replaceState(null, "", START);
});

describe("takeLinkParams", () => {
  it("returns the password and source and removes both from the address bar", () => {
    visit("?password=open%20sesame&pwsource=alice");
    const replaceState = vi.spyOn(window.history, "replaceState");

    expect(takeLinkParams()).toEqual({ password: "open sesame", source: "alice" });

    expect(replaceState).toHaveBeenCalledTimes(1);
    expect(window.location.search).toBe("");
    expect(window.location.pathname).toBe("/demo");
    expect(window.location.hash).toBe("#results");
  });

  it("keeps the other parameters", () => {
    visit("?run=r1&password=open%20sesame&tab=compare");

    expect(takeLinkParams()).toEqual({ password: "open sesame", source: null });

    const params = new URLSearchParams(window.location.search);
    expect(params.has("password")).toBe(false);
    expect(params.get("run")).toBe("r1");
    expect(params.get("tab")).toBe("compare");
  });

  it("removes the source alone when the link has no password", () => {
    visit("?pwsource=alice&run=r1");

    expect(takeLinkParams()).toEqual({ password: null, source: "alice" });

    expect(window.location.search).toBe("?run=r1");
  });

  it("changes nothing when neither parameter is present", () => {
    visit("?run=r1");
    const replaceState = vi.spyOn(window.history, "replaceState");

    expect(takeLinkParams()).toEqual({ password: null, source: null });

    expect(replaceState).not.toHaveBeenCalled();
    expect(window.location.search).toBe("?run=r1");
  });

  it("still returns the values when the URL cannot be rewritten", () => {
    visit("?password=open%20sesame&pwsource=alice");
    vi.spyOn(window.history, "replaceState").mockImplementation(() => {
      throw new Error("blocked");
    });

    expect(takeLinkParams()).toEqual({ password: "open sesame", source: "alice" });
  });
});

describe("the link source", () => {
  it("is empty until one is set, then remembered for the tab, then forgotten", () => {
    expect(getSource()).toBeNull();

    setSource("alice");
    expect(getSource()).toBe("alice");
    expect(window.sessionStorage.getItem("ct-link-source")).toBe("alice");

    clearSource();
    expect(window.sessionStorage.getItem("ct-link-source")).toBeNull();
    // Storage is empty, so this also shows the in-memory copy was cleared.
    expect(getSource()).toBeNull();
  });

  it("still works for this page when the browser refuses storage", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new Error("blocked");
    });

    setSource("alice");
    expect(getSource()).toBe("alice");
    clearSource();
    expect(getSource()).toBeNull();
  });

  it("falls back to the in-memory copy when storage could not be written", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });

    setSource("alice");

    expect(window.sessionStorage.getItem("ct-link-source")).toBeNull();
    expect(getSource()).toBe("alice");
  });
});
