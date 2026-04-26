/**
 * HTTP client shared across all vite-fastapi-sqlite apps.
 *
 * The backend URL is injected by Forger via VITE_API_BASE_URL at runtime.
 * Falls back to localhost:8000 for local development.
 */

const RAW_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
export const API_BASE_URL = RAW_BASE.replace(/\/+$/, "");

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, message: string, body?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

type RequestOptions = {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
};

export async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");

  let body: BodyInit | undefined;
  if (options.body !== undefined && options.body !== null) {
    if (typeof FormData !== "undefined" && options.body instanceof FormData) {
      body = options.body;
    } else {
      body = JSON.stringify(options.body);
      headers.set("Content-Type", "application/json");
    }
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: options.method ?? "GET",
      body,
      headers,
      signal: options.signal,
    });
  } catch (error) {
    throw new ApiError(0, "Network error", error);
  }

  if (response.status === 204) return undefined as T;

  const contentType = response.headers.get("Content-Type") ?? "";
  const payload: unknown = contentType.includes("application/json")
    ? await response.json().catch(() => null)
    : await response.text().catch(() => null);

  if (!response.ok) {
    const detail =
      payload && typeof payload === "object" && "detail" in payload
        ? String((payload as { detail: unknown }).detail)
        : `HTTP ${response.status}`;
    throw new ApiError(response.status, detail, payload);
  }

  return payload as T;
}

export const get  = <T>(path: string, signal?: AbortSignal) => request<T>(path, { signal });
export const post = <T>(path: string, body: unknown, signal?: AbortSignal) => request<T>(path, { method: "POST", body, signal });
export const patch = <T>(path: string, body: unknown, signal?: AbortSignal) => request<T>(path, { method: "PATCH", body, signal });
export const put  = <T>(path: string, body: unknown, signal?: AbortSignal) => request<T>(path, { method: "PUT", body, signal });
export const del  = <T>(path: string, signal?: AbortSignal) => request<T>(path, { method: "DELETE", signal });
