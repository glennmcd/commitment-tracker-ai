import { startEvalRun } from "@/lib/evalRuns";
import { describe, expect, it } from "vitest";
import { fakeClient, ok } from "@/lib/jobs.test";
import { RUN_ID, runStatus } from "@/test/evalRunFixtures";

describe("startEvalRun", () => {
  it("posts the set, configuration and offline flag, and returns the run",
    async () => {
      const { client, post } = fakeClient([ok(runStatus({ status: "queued" }), 202)]);
      const choice = { set: "test", configuration: "haiku", offline: true };
      const result = await startEvalRun(client, choice);
      expect(post).toHaveBeenCalledWith("/eval-runs", { body: choice });
      expect(result).toMatchObject({ ok: true, job: { run_id: RUN_ID, status: "queued" } });
    });

  // it.each([
  //   ["cache_miss", 404, "The requested cache entry was not found."]
  // ])("explains %s", async (code, status, message) => {
  //   const { client } = fakeClient([failure(code, status)]);
  //   expect(await startEvalRun(client, { set: "test", configuration: "haiku", offline: true })).toEqual({ ok: false, message });
  // });
  function failure(code: string, status: number, headers: HeadersInit = {}) {
    return {
      error: { error: { code, message: "m", details: [] } },
      response: new Response(null, { status, headers }),
    };
  }



});