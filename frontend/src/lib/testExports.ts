import { vi } from "vitest";
import type { ApiClient } from "@/api/client";

/** A client whose calls return the scripted responses in order. */
export function fakeClient(posts: unknown[], gets: unknown[] = []) {
  const post = vi.fn(async () => posts.shift());
  const get = vi.fn(async () => gets.shift());
  return { client: { POST: post, GET: get } as unknown as ApiClient, post, get };
}

export const ok = (data: unknown, status = 200) => ({ data, response: new Response(null, { status }) });

export const failure = (code: string, status: number, headers: HeadersInit = {}) => ({
  error: { error: { code, message: "m", details: [] } },
  response: new Response(null, { status, headers }),
});
