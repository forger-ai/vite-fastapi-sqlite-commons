import { expect, vi, type Mock } from "vitest";

type FetchLike = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export type FetchMock = Mock<FetchLike>;

export function createFetchMock(): FetchMock {
  const fetchMock = vi.fn<FetchLike>();
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

export function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  return new Response(JSON.stringify(body), {
    ...init,
    headers,
  });
}

export function textResponse(body: string, init: ResponseInit = {}): Response {
  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "text/plain");
  }

  return new Response(body, {
    ...init,
    headers,
  });
}

export function noContentResponse(init: ResponseInit = {}): Response {
  return new Response(null, {
    ...init,
    status: init.status ?? 204,
  });
}

export function lastFetchRequest(fetchMock: FetchMock) {
  expect(fetchMock).toHaveBeenCalled();

  const [input, init] = fetchMock.mock.calls.at(-1) ?? [];
  const requestInit = init ?? {};

  return {
    headers: new Headers(requestInit.headers),
    init: requestInit,
    url: String(input),
  };
}
