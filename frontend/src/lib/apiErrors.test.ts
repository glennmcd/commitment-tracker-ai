import { describe, expect, it } from "vitest";
import spec from "../../../openapi.json";
import { codeOf, explain, explainFailure, FORBIDDEN, GATEWAY_TIMEOUT, GENERIC } from "./apiErrors";
import { failure, gatewayFailure } from "./testExports";

const schemas = spec.components.schemas as Record<string, { enum?: string[] }>;
const CODES = schemas.ErrorCode?.enum ?? [];

describe("error codes from openapi.json", () => {
  it("reads the codes from the schema", () => expect(CODES.length).toBeGreaterThan(10));

  it.each(CODES)("%s has a sentence for the visitor", (code) => {
    expect(codeOf({ error: { code } })).toBe(code);
    expect(explain(code, null)).not.toBe(GENERIC);
  });

  it("knows the worker's failure codes too", () => {
    expect(explain("no_speech", null)).toBe("No speech was found in the recording.");
    expect(explain("transcription_failed", null)).toBe("The recording could not be transcribed.");
  });

  it("falls back for a code the schema does not define", () => {
    expect(codeOf({ error: { code: "brand_new" } })).toBeUndefined();
    expect(explain("brand_new", null)).toBe(GENERIC);
    expect(explain(null, null)).toBe(GENERIC);
  });
});

describe("explainFailure", () => {
  it("uses the app's error code and its Retry-After header", () => {
    const { error, response } = failure("rate_limited", 429, { "retry-after": "30" });
    expect(explainFailure(error, response)).toBe("Too many requests. Try again in 30 seconds.");
  });

  it("lets a caller reword a code", () => {
    const { error, response } = failure("job_not_found", 404);
    expect(explainFailure(error, response, { job_not_found: "Gone." })).toBe("Gone.");
  });

  it("explains the authorizer's 403 from API Gateway", () => {
    const { error, response } = gatewayFailure(403, "Forbidden");
    expect(explainFailure(error, response)).toBe(FORBIDDEN);
  });

  it("explains API Gateway's 504 timeout", () => {
    const { error, response } = gatewayFailure(504, "Gateway Timeout");
    expect(explainFailure(error, response)).toBe(GATEWAY_TIMEOUT);
  });

  it("falls back when the body is neither", () => {
    expect(explainFailure(undefined, new Response(null, { status: 500 }))).toBe(GENERIC);
  });
});
