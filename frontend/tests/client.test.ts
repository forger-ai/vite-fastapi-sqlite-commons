import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createFetchMock,
  jsonResponse,
  lastFetchRequest,
  noContentResponse,
  textResponse,
  type FetchMock,
} from "../testing/fetchMock";

async function importClient(baseUrl?: string) {
  vi.resetModules();

  if (baseUrl !== undefined) {
    vi.stubEnv("VITE_API_BASE_URL", baseUrl);
  }

  return import("../client");
}

afterEach(() => {
  vi.resetModules();
  vi.doUnmock("../remoteTunnel");
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("commons frontend client", () => {
  it("sends JSON requests with the default headers and parses JSON responses", async () => {
    const fetchMock = createFetchMock();
    const { post } = await importClient("http://api.test");
    fetchMock.mockResolvedValueOnce(jsonResponse({ id: 42 }));

    const result = await post<{ id: number }>("/items", { name: "Notebook" });

    expect(result).toEqual({ id: 42 });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    const request = lastFetchRequest(fetchMock);
    expect(request.url).toBe("http://api.test/items");
    expect(request.init.method).toBe("POST");
    expect(request.init.body).toBe(JSON.stringify({ name: "Notebook" }));
    expect(request.headers.get("Accept")).toBe("application/json");
    expect(request.headers.get("Content-Type")).toBe("application/json");
  });

  it("sends FormData without forcing a JSON content type", async () => {
    const fetchMock = createFetchMock();
    const { post } = await importClient("http://api.test");
    const formData = new FormData();
    formData.append("title", "Receipt");
    formData.append("file", new Blob(["file contents"]), "receipt.txt");
    fetchMock.mockResolvedValueOnce(jsonResponse({ uploaded: true }));

    const result = await post<{ uploaded: boolean }>("/uploads", formData);

    expect(result).toEqual({ uploaded: true });

    const request = lastFetchRequest(fetchMock);
    expect(request.url).toBe("http://api.test/uploads");
    expect(request.init.method).toBe("POST");
    expect(request.init.body).toBe(formData);
    expect(request.headers.get("Accept")).toBe("application/json");
    expect(request.headers.has("Content-Type")).toBe(false);
  });

  it("sends FormData through remote RPC with its generated multipart content type", async () => {
    let capturedRequest: unknown = null;
    vi.doMock("../remoteTunnel", () => ({
      isForgerRemoteTunnel: () => true,
      remoteFetch: vi.fn(async (input: unknown) => {
        capturedRequest = input;
        return jsonResponse({ uploaded: true });
      }),
    }));
    const { post } = await importClient("http://api.test");
    const formData = new FormData();
    formData.append("title", "Receipt");
    formData.append("file", new Blob(["file contents"]), "receipt.txt");

    const result = await post<{ uploaded: boolean }>("/uploads", formData);

    expect(result).toEqual({ uploaded: true });
    expect(capturedRequest).toMatchObject({
      method: "POST",
      path: "/uploads",
    });
    const headers = (capturedRequest as { headers: Record<string, string> }).headers;
    expect(headers["content-type"]).toContain("multipart/form-data; boundary=");
    expect((capturedRequest as { bodyBase64: string | null }).bodyBase64).toEqual(expect.any(String));
  });

  it("returns undefined for 204 responses", async () => {
    const fetchMock = createFetchMock();
    const { del } = await importClient("http://api.test");
    fetchMock.mockResolvedValueOnce(noContentResponse());

    await expect(del<void>("/items/42")).resolves.toBeUndefined();

    const request = lastFetchRequest(fetchMock);
    expect(request.url).toBe("http://api.test/items/42");
    expect(request.init.method).toBe("DELETE");
  });

  it("raises ApiError with JSON detail payloads", async () => {
    const fetchMock = createFetchMock();
    const { get, ApiError } = await importClient("http://api.test");
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "Item not found" }, { status: 404 }),
    );

    const error = await get("/items/missing").catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      body: { detail: "Item not found" },
      message: "Item not found",
      name: "ApiError",
      status: 404,
    });
  });

  it("formats object JSON detail payloads instead of showing object placeholders", async () => {
    const fetchMock = createFetchMock();
    const { get } = await importClient("http://api.test");
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: { error: "Invalid upload", field: "file" } }, { status: 422 }),
    );

    await expect(get("/uploads/missing")).rejects.toMatchObject({
      body: { detail: { error: "Invalid upload", field: "file" } },
      message: JSON.stringify({ error: "Invalid upload", field: "file" }),
      name: "ApiError",
      status: 422,
    });
  });

  it("raises ApiError with text error payloads", async () => {
    const fetchMock = createFetchMock();
    const { patch } = await importClient("http://api.test");
    fetchMock.mockResolvedValueOnce(
      textResponse("upstream unavailable", { status: 502 }),
    );

    await expect(patch("/items/42", { title: "Updated" })).rejects.toMatchObject({
      body: "upstream unavailable",
      message: "HTTP 502",
      name: "ApiError",
      status: 502,
    });
  });

  it("wraps fetch failures as network ApiError instances", async () => {
    const fetchMock = createFetchMock();
    const { get } = await importClient("http://api.test");
    const networkError = new TypeError("fetch failed");
    fetchMock.mockRejectedValueOnce(networkError);

    await expect(get("/health")).rejects.toMatchObject({
      body: networkError,
      message: "Network error",
      name: "ApiError",
      status: 0,
    });
  });

  it("falls back to localhost and trims custom base URL trailing slashes", async () => {
    const defaultFetchMock = createFetchMock();
    const defaultClient = await importClient();
    defaultFetchMock.mockResolvedValueOnce(jsonResponse({ ok: true }));

    expect(defaultClient.API_BASE_URL).toBe("http://localhost:8000");
    await defaultClient.get("/health");
    expect(lastFetchRequest(defaultFetchMock).url).toBe("http://localhost:8000/health");

    const customFetchMock = createFetchMock();
    const customClient = await importClient("http://api.test///");
    customFetchMock.mockResolvedValueOnce(jsonResponse({ ok: true }));

    expect(customClient.API_BASE_URL).toBe("http://api.test");
    await customClient.get("/health");
    expect(lastFetchRequest(customFetchMock).url).toBe("http://api.test/health");
  });

  it("builds websocket API URLs while preserving runtime proxy prefixes", async () => {
    const localClient = await importClient("http://localhost:8000");
    expect(localClient.apiWebSocketUrl("/api/realtime/ws")).toBe("ws://localhost:8000/api/realtime/ws");

    const installedClient = await importClient("http://127.0.0.1:56075/__forger_api");
    expect(installedClient.apiWebSocketUrl("/api/voice/live-transcripts/ws", {
      language: "es",
      deviceId: "Built In Microphone",
      empty: null,
    })).toBe(
      "ws://127.0.0.1:56075/__forger_api/api/voice/live-transcripts/ws?language=es&deviceId=Built+In+Microphone",
    );

    const secureClient = await importClient("https://api.test/base///");
    expect(secureClient.apiWebSocketUrl("api/realtime/ws")).toBe("wss://api.test/base/api/realtime/ws");
  });

  it("passes abort signals through to fetch", async () => {
    const fetchMock: FetchMock = createFetchMock();
    const { get } = await importClient("http://api.test");
    const controller = new AbortController();
    fetchMock.mockResolvedValueOnce(jsonResponse({ ok: true }));

    await get("/items", controller.signal);

    expect(lastFetchRequest(fetchMock).init.signal).toBe(controller.signal);
  });
});
