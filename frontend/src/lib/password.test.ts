import { afterEach, describe, expect, it, vi } from "vitest";
import { clearPassword, getPassword, PASSWORD_REJECTED, passwordRejected, setPassword } from "./password";

afterEach(() => {
  clearPassword();
  vi.restoreAllMocks();
});

describe("the site password", () => {
  it("is empty until one is set, then remembered for the tab, then forgotten", () => {
    expect(getPassword()).toBeNull();

    setPassword("open sesame");
    expect(getPassword()).toBe("open sesame");
    expect(window.sessionStorage.getItem("ct-site-password")).toBe("open sesame");

    clearPassword();
    expect(getPassword()).toBeNull();
    expect(window.sessionStorage.getItem("ct-site-password")).toBeNull();
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

    setPassword("open sesame");
    expect(getPassword()).toBe("open sesame");
    clearPassword();
    expect(getPassword()).toBeNull();
  });

  it("announces a rejection to the page", () => {
    const heard = vi.fn();
    window.addEventListener(PASSWORD_REJECTED, heard);

    passwordRejected();

    expect(heard).toHaveBeenCalledTimes(1);
    window.removeEventListener(PASSWORD_REJECTED, heard);
  });
});
