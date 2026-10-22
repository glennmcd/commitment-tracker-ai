import createClient from "openapi-fetch";
import type { paths } from "./schema";

/** The API address is missing or not a usable http(s) address. */
export class ApiConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ApiConfigError";
  }
}

/**
 * The API's base address without a trailing slash. It comes from NEXT_PUBLIC_API_BASE_URL, which Next writes into the
 * bundle at build time (Amplify sets it from the API stack's output). The address is passed in so tests can supply
 * one; callers pass `process.env.NEXT_PUBLIC_API_BASE_URL` literally, which is the form Next replaces.
 */
export function apiBaseUrl(value: string | undefined): string {
  const trimmed = value?.trim();
  if (!trimmed) {
    throw new ApiConfigError("NEXT_PUBLIC_API_BASE_URL is not set, so the site does not know where the API is.");
  }
  let url: URL;
  try {
    url = new URL(trimmed);
  } catch {
    throw new ApiConfigError("NEXT_PUBLIC_API_BASE_URL is not a valid address.");
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") {
    throw new ApiConfigError("NEXT_PUBLIC_API_BASE_URL must start with https:// or http://.");
  }
  return trimmed.replace(/\/+$/, "");
}

type Fetch = (input: Request) => Promise<Response>;

/** A client typed from openapi.json (`bun run gen:api` regenerates ./schema.d.ts). */
export function createApiClient(baseUrl: string, fetchImpl?: Fetch) {
  return createClient<paths>({ baseUrl, ...(fetchImpl ? { fetch: fetchImpl } : {}) });
}

export type ApiClient = ReturnType<typeof createApiClient>;

/** The client for this deployment. Read when first used in the browser, so a build without the variable still works. */
export function getApiClient(): ApiClient {
  return createApiClient(apiBaseUrl(process.env.NEXT_PUBLIC_API_BASE_URL));
}
