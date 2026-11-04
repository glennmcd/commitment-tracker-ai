import type { components } from "@/api/schema";

/** The API's error shapes, as the OpenAPI schema defines them (openapi.json, generated into schema.d.ts). */
export type ErrorCode = components["schemas"]["ErrorCode"];
export type ErrorBody = components["schemas"]["ErrorResponse"];
/** What API Gateway sends when it answers instead of the app: a 403 from the authorizer, a 504 on timeout. */
export type GatewayError = components["schemas"]["GatewayErrorResponse"];
/** Failure codes the worker stores on a job (`Job.error_code` is a plain string in the schema). */
export type WorkerErrorCode = "transcription_failed" | "no_speech";

export const NETWORK = "Could not reach the API. Check your connection and try again.";
export const GENERIC = "Something went wrong. Try again.";
export const FORBIDDEN = "The site password was not accepted. Reload the page and enter it again.";
export const GATEWAY_TIMEOUT = "The request took too long. Try again.";

/** What the visitor reads for each code. The type is exhaustive, so a code added to the API fails the build here. */
const MESSAGES: Record<ErrorCode | WorkerErrorCode, string> = {
  validation_error: "The API did not accept that request.",
  rate_limited: "Too many requests. Try again in a moment.",
  daily_budget_exhausted: "The demo has reached its daily limit. Try again tomorrow.",
  model_unavailable: "The model is unavailable right now. Try again in a minute.",
  model_output_invalid: "The model's answer could not be read. Try again.",
  model_refused: "The model declined to analyse this text.",
  extraction_failed: "The text could not be analysed. Try again.",
  uploads_unavailable: "Recording is not available right now.",
  upload_not_found: "The upload expired. Record again.",
  sample_not_found: "That sample clip is not available.",
  audio_too_long: "That recording is longer than 60 seconds.",
  audio_invalid: "That recording could not be read. Try recording again.",
  jobs_unavailable: "The demo is not available right now.",
  job_not_found: "That job has expired. Run it again.",
  job_not_finished: "That job has no results to give feedback on.",
  span_not_found: "That result is no longer there.",
  imports_disabled: "Imports are disabled on this server.",
  batch_exists: "That batch already exists. Choose another name.",
  invalid_import_options: "The batch name or provenance breaks a rule.",
  batch_empty: "Nothing in that batch could be imported.",
  transcription_failed: "The recording could not be transcribed.",
  no_speech: "No speech was found in the recording.",
};

/** The code in an error body, when it is one the schema defines. */
export function codeOf(error: unknown): ErrorCode | undefined {
  const code = (error as Partial<ErrorBody> | undefined)?.error?.code;
  return typeof code === "string" && Object.hasOwn(MESSAGES, code) ? code : undefined;
}

export function explain(
  code: string | null | undefined,
  retryAfter: string | null,
  overrides: Partial<Record<ErrorCode, string>> = {},
): string {
  if (!code || !Object.hasOwn(MESSAGES, code)) return GENERIC;
  if (code in overrides) return overrides[code as ErrorCode] as string;
  if (code === "rate_limited" && retryAfter) return `Too many requests. Try again in ${retryAfter} seconds.`;
  return MESSAGES[code as ErrorCode | WorkerErrorCode];
}

/**
 * The sentence for a failed call: the code in the app's error body, or else the status API Gateway answered with
 * (403 from the password authorizer, 504 on timeout).
 */
export function explainFailure(
  error: unknown,
  response: Response,
  overrides: Partial<Record<ErrorCode, string>> = {},
): string {
  const code = codeOf(error);
  if (code) return explain(code, response.headers.get("retry-after"), overrides);
  if (response.status === 403) return FORBIDDEN;
  if (response.status === 504) return GATEWAY_TIMEOUT;
  return GENERIC;
}
