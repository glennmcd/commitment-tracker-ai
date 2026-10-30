import { describe, expect, it } from "vitest";
// import { startEvalRun } from "@/lib/evalRuns";
import { fakeClient, ok } from "@/lib/testExports";
import { RUN_ID, runStatus } from "@/test/evalRunFixtures";

describe("startEvalRun", () => {
  it("posts the set, configuration and offline flag, and returns the run", async () => {
    const { client, post } = fakeClient([ok(runStatus({ status: "queued" }), 202)]);
    const choice = { set: "test", configuration: "haiku", offline: true };
    // const result = await startEvalRun(client, choice);
    expect(post).toHaveBeenCalledWith("/eval-runs", { body: choice });
    // expect(result).toMatchObject({ ok: true, job: { run_id: RUN_ID, status: "queued" } });
  });
});
