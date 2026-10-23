import { describe, expect, it, mock, spyOn } from "bun:test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const handlerPath = path.join(path.dirname(fileURLToPath(import.meta.url)), "../lambda/authorizer/index.mjs");

interface Handler {
  createHandler(deps: {
    getPassword(): Promise<string | undefined>;
  }): (event: { headers?: Record<string, string | undefined> }) => Promise<{ isAuthorized: boolean }>;
}

// Imported by path so the plain JavaScript Lambda needs no type declarations.
const { createHandler } = (await import(handlerPath)) as Handler;

const withHeader = (value: string | undefined) => ({ headers: value === undefined ? {} : { authorization: value } });

describe("authorizer handler", () => {
  it("allows the request that carries the password", async () => {
    const handler = createHandler({ getPassword: async () => "open sesame" });
    expect(await handler(withHeader("open sesame"))).toEqual({ isAuthorized: true });
  });

  it.each([undefined, "", "open sesame!", "OPEN SESAME", "open", "Bearer open sesame"])(
    "denies the header %p",
    async (value) => {
      const handler = createHandler({ getPassword: async () => "open sesame" });
      expect(await handler(withHeader(value))).toEqual({ isAuthorized: false });
    },
  );

  it("denies a request with no headers object at all", async () => {
    const handler = createHandler({ getPassword: async () => "open sesame" });
    expect(await handler({})).toEqual({ isAuthorized: false });
  });

  it.each(["alpha", "beta gamma", "delta"])("allows any one of several passwords: %p", async (given) => {
    const handler = createHandler({ getPassword: async () => "alpha\r\nbeta gamma\n\ndelta\n" });
    expect(await handler(withHeader(given))).toEqual({ isAuthorized: true });
  });

  it.each(["", "beta", "alpha\nbeta gamma", "gamma"])("denies %p when several passwords are stored", async (given) => {
    const handler = createHandler({ getPassword: async () => "alpha\nbeta gamma\ndelta" });
    expect(await handler(withHeader(given))).toEqual({ isAuthorized: false });
  });

  it.each([undefined, "", "\n\n"])("denies everything when the stored password is %p", async (stored) => {
    const handler = createHandler({ getPassword: async () => stored });
    expect(await handler(withHeader(""))).toEqual({ isAuthorized: false });
    expect(await handler(withHeader("anything"))).toEqual({ isAuthorized: false });
  });

  it("denies, and logs only the error message, when the password cannot be read", async () => {
    const error = spyOn(console, "error").mockImplementation(() => {});
    const handler = createHandler({
      getPassword: async () => {
        throw new Error("ParameterNotFound");
      },
    });

    expect(await handler(withHeader("open sesame"))).toEqual({ isAuthorized: false });
    const logged = JSON.stringify(error.mock.calls);
    expect(logged).toContain("ParameterNotFound");
    expect(logged).not.toContain("open sesame");
    error.mockRestore();
  });

  it("reads the password once while it works, and tries again after a failure", async () => {
    const quiet = spyOn(console, "error").mockImplementation(() => {});
    const getPassword = mock<() => Promise<string | undefined>>()
      .mockRejectedValueOnce(new Error("throttled"))
      .mockResolvedValue("open sesame");
    const handler = createHandler({ getPassword });

    expect(await handler(withHeader("open sesame"))).toEqual({ isAuthorized: false });
    expect(await handler(withHeader("open sesame"))).toEqual({ isAuthorized: true });
    expect(await handler(withHeader("nope"))).toEqual({ isAuthorized: false });
    expect(getPassword).toHaveBeenCalledTimes(2);
    quiet.mockRestore();
  });

  it("never logs the header it was given", async () => {
    const log = spyOn(console, "log").mockImplementation(() => {});
    const warn = spyOn(console, "warn").mockImplementation(() => {});
    const handler = createHandler({ getPassword: async () => "open sesame" });
    await handler(withHeader("guess-123"));
    expect(JSON.stringify([...log.mock.calls, ...warn.mock.calls])).not.toContain("guess-123");
    log.mockRestore();
    warn.mockRestore();
  });
});
