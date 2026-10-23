import { afterEach, describe, expect, it, vi } from "vitest";
import { clearPassword, getPassword, PASSWORD_REJECTED, setPassword } from "@/lib/password";
import { ApiConfigError, apiBaseUrl, createApiClient } from "./client";

describe("apiBaseUrl", () => {
  it("returns an http or https address without a trailing slash", () => {
    expect(apiBaseUrl("https://api.example.com")).toBe("https://api.example.com");
    expect(apiBaseUrl("https://api.example.com/")).toBe("https://api.example.com");
    expect(apiBaseUrl("http://localhost:8000//")).toBe("http://localhost:8000");
    expect(apiBaseUrl(" https://api.example.com/v1/ ")).toBe("https://api.example.com/v1");
  });

  it.each([undefined, "", "   "])("names the variable when it is %p", (value) => {
    expect(() => apiBaseUrl(value)).toThrow(ApiConfigError);
    expect(() => apiBaseUrl(value)).toThrow("NEXT_PUBLIC_API_BASE_URL");
  });

  it.each(["not a url", "ftp://example.com", "javascript:alert(1)", "//example.com"])("rejects %p", (value) => {
    expect(() => apiBaseUrl(value)).toThrow(ApiConfigError);
  });
});

function recordingFetch(response: Response) {
  const requests: Request[] = [];
  const fetchImpl = async (input: Request | URL | string): Promise<Response> => {
    requests.push(input instanceof Request ? input : new Request(input));
    // A clone, so one canned response can answer several requests.
    return response.clone();
  };
  return { requests, fetchImpl };
}

describe("createApiClient", () => {
  it("calls the API at the base address and types the response from openapi.json", async () => {
    const { requests, fetchImpl } = recordingFetch(
      Response.json({ status: "ok", model: "claude-haiku-5-5", prompt_version: "v1" }),
    );
    const client = createApiClient("https://api.example.com", fetchImpl);

    const { data, error } = await client.GET("/health");

    expect(requests.map((r) => `${r.method} ${r.url}`)).toEqual(["GET https://api.example.com/health"]);
    expect(error).toBeUndefined();
    // These property accesses compile only because the generated schema describes the response.
    expect(data?.status).toBe("ok");
    expect(data?.prompt_version).toBe("v1");
  });

  describe("with a site password", () => {
    afterEach(() => clearPassword());

    it("sends it as the Authorization header on every request", async () => {
      setPassword("open sesame");
      const { requests, fetchImpl } = recordingFetch(Response.json([]));
      const client = createApiClient("https://api.example.com", fetchImpl);

      await client.GET("/samples");
      await client.POST("/uploads");

      expect(requests.map((r) => r.headers.get("authorization"))).toEqual(["open sesame", "open sesame"]);
    });

    it("sends no Authorization header before one is entered", async () => {
      const { requests, fetchImpl } = recordingFetch(Response.json([]));

      await createApiClient("https://api.example.com", fetchImpl).GET("/samples");

      expect(requests[0]?.headers.has("authorization")).toBe(false);
    });

    it.each([401, 403])("forgets it and tells the page when the API answers %i", async (status) => {
      setPassword("wrong");
      const heard = vi.fn();
      window.addEventListener(PASSWORD_REJECTED, heard);
      const { fetchImpl } = recordingFetch(new Response(null, { status }));

      await createApiClient("https://api.example.com", fetchImpl).GET("/samples");

      expect(getPassword()).toBeNull();
      expect(heard).toHaveBeenCalledTimes(1);
      window.removeEventListener(PASSWORD_REJECTED, heard);
    });

    it.each([200, 404, 429, 500])("keeps it when the API answers %i", async (status) => {
      setPassword("open sesame");
      const heard = vi.fn();
      window.addEventListener(PASSWORD_REJECTED, heard);
      const { fetchImpl } = recordingFetch(new Response(null, { status }));

      await createApiClient("https://api.example.com", fetchImpl).GET("/samples");

      expect(getPassword()).toBe("open sesame");
      expect(heard).not.toHaveBeenCalled();
      window.removeEventListener(PASSWORD_REJECTED, heard);
    });
  });

  it("returns the API's error body as data, not an exception", async () => {
    const body = { error: { code: "rate_limited", message: "Too many requests.", details: [] } };
    const { fetchImpl } = recordingFetch(Response.json(body, { status: 429, headers: { "retry-after": "30" } }));
    const client = createApiClient("https://api.example.com", fetchImpl);

    const { data, error, response } = await client.POST("/uploads");

    expect(data).toBeUndefined();
    expect(response.status).toBe(429);
    expect(response.headers.get("retry-after")).toBe("30");
    expect(error).toMatchObject(body);
  });
});
