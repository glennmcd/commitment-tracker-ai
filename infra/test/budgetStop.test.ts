import { describe, expect, it } from "bun:test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const handlerPath = path.join(path.dirname(fileURLToPath(import.meta.url)), "../lambda/budget-stop/index.mjs");

interface Handler {
  createHandler(deps: {
    setConcurrency(functionName: string, limit: number): Promise<unknown>;
    functionNames?: string;
  }): () => Promise<{ stopped: string[] }>;
}

// Imported by path so the plain JavaScript Lambda needs no type declarations.
const { createHandler } = (await import(handlerPath)) as Handler;

describe("budget stop handler", () => {
  it("sets the reserved concurrency of every named function to 0", async () => {
    const calls: [string, number][] = [];
    const handler = createHandler({
      setConcurrency: async (name, limit) => {
        calls.push([name, limit]);
      },
      functionNames: "api-fn,worker-fn",
    });

    expect(await handler()).toEqual({ stopped: ["api-fn", "worker-fn"] });
    expect(calls).toEqual([
      ["api-fn", 0],
      ["worker-fn", 0],
    ]);
  });

  it("ignores spaces and empty entries in the list", async () => {
    const names: string[] = [];
    const handler = createHandler({
      setConcurrency: async (name) => {
        names.push(name);
      },
      functionNames: " a , ,b,",
    });
    await handler();
    expect(names).toEqual(["a", "b"]);
  });

  it.each([undefined, "", " , "])("fails fast when the function names are %p", (value) => {
    expect(() => createHandler({ setConcurrency: async () => {}, functionNames: value })).toThrow("FUNCTION_NAMES");
  });

  it("still stops the others when one fails, then reports the failure so it is retried", async () => {
    const stopped: string[] = [];
    const handler = createHandler({
      setConcurrency: async (name) => {
        if (name === "first") throw new Error("AccessDenied");
        stopped.push(name);
      },
      functionNames: "first,second",
    });

    await expect(handler()).rejects.toThrow("first: AccessDenied");
    expect(stopped).toEqual(["second"]);
  });
});
