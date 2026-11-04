import { vi } from "vitest";
import type { ApiClient } from "@/api/client";
import type { ErrorBody, ErrorCode, GatewayError } from "./apiErrors";

/** A client whose calls return the scripted responses in order. */
export function fakeClient(posts: unknown[], gets: unknown[] = []) {
  const post = vi.fn(async () => posts.shift());
  const get = vi.fn(async () => gets.shift());
  return { client: { POST: post, GET: get } as unknown as ApiClient, post, get };
}

export const ok = <T>(data: T, status = 200) => ({ data, response: new Response(null, { status }) });

/** An error body built to the schema's `ErrorResponse`, so a code the API no longer sends fails to compile. */
export const failure = (code: ErrorCode, status: number, headers: HeadersInit = {}) => ({
  error: { error: { code, message: "m", details: [] } } satisfies ErrorBody,
  response: new Response(null, { status, headers }),
});

/** What API Gateway sends: the authorizer's 403 or a 504 timeout, with no app error body. */
export const gatewayFailure = (status: 403 | 504, message: string) => ({
  error: { message } satisfies GatewayError,
  response: new Response(null, { status }),
});
