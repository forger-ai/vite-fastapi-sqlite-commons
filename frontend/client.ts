/**
 * HTTP client shared across all vite-fastapi-sqlite apps.
 *
 * The backend URL is injected by Forger via VITE_API_BASE_URL at runtime.
 * Falls back to localhost:8000 for local development.
 */

const RAW_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
export const API_BASE_URL = RAW_BASE.replace(/\/+$/, "");

import { isForgerRemoteTunnel, remoteFetch } from "./remoteTunnel";

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
    const method = options.method ?? "GET";
    if (isForgerRemoteTunnel()) {
      const remoteBody = await serializeBodyForRemote(body);
      if (remoteBody.contentType && !headers.has("Content-Type")) {
        headers.set("Content-Type", remoteBody.contentType);
      }
      response = await remoteFetch({
        method,
        path,
        headers: Object.fromEntries(headers.entries()),
        bodyBase64: remoteBody.bodyBase64,
      }, options.signal);
    } else {
      response = await fetch(`${API_BASE_URL}${path}`, {
        method,
        body,
        headers,
        signal: options.signal,
      });
    }
  } catch (error) {
    throw new ApiError(0, "Network error", error);
  }

  if (response.status === 204) return undefined as T;

  const contentType = response.headers.get("Content-Type") ?? "";
  const payload: unknown = contentType.includes("application/json")
    ? await response.json().catch(() => null)
    : await response.text().catch(() => null);

  if (!response.ok) {
    throw new ApiError(response.status, errorMessageFromPayload(payload, `HTTP ${response.status}`), payload);
  }

  return payload as T;
}

export const get  = <T>(path: string, signal?: AbortSignal) => request<T>(path, { signal });
export const post = <T>(path: string, body: unknown, signal?: AbortSignal) => request<T>(path, { method: "POST", body, signal });
export const patch = <T>(path: string, body: unknown, signal?: AbortSignal) => request<T>(path, { method: "PATCH", body, signal });
export const put  = <T>(path: string, body: unknown, signal?: AbortSignal) => request<T>(path, { method: "PUT", body, signal });
export const del  = <T>(path: string, signal?: AbortSignal) => request<T>(path, { method: "DELETE", signal });

type SerializedRemoteBody = {
  bodyBase64: string | null;
  contentType?: string;
};

async function serializeBodyForRemote(body: BodyInit | undefined): Promise<SerializedRemoteBody> {
  if (body === undefined) {
    return { bodyBase64: null };
  }
  if (typeof body === "string") {
    return { bodyBase64: btoa(unescape(encodeURIComponent(body))) };
  }
  const response = new Response(body);
  return {
    bodyBase64: bytesToBase64(new Uint8Array(await response.arrayBuffer())),
    contentType: response.headers.get("Content-Type") ?? undefined,
  };
}

function errorMessageFromPayload(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object" || !("detail" in payload)) {
    return fallback;
  }
  return stringifyErrorDetail((payload as { detail: unknown }).detail) ?? fallback;
}

function stringifyErrorDetail(detail: unknown): string | null {
  if (typeof detail === "string") {
    return detail;
  }
  if (typeof detail === "number" || typeof detail === "boolean") {
    return String(detail);
  }
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => stringifyErrorDetail(item)).filter(Boolean);
    return parts.length > 0 ? parts.join("; ") : null;
  }
  if (detail && typeof detail === "object") {
    return JSON.stringify(detail);
  }
  return null;
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return btoa(binary);
}
