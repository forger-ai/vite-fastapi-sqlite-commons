export const REMOTE_RPC_PATH = "/__forger_remote_rpc";
export const REMOTE_WS_PATH = "/__forger_remote_ws";

import { FORGER_LOGO_SVG } from "./forgerBrand";

const REMOTE_FLAG = import.meta.env.VITE_FORGER_REMOTE_TUNNEL === "true";
const REMOTE_SESSION_ID = import.meta.env.VITE_FORGER_REMOTE_SESSION_ID ?? "";
const REMOTE_HANDSHAKE_URL = import.meta.env.VITE_FORGER_CLOUD_HANDSHAKE_URL ?? "";

export type RemoteHandshake = {
  sessionId: string;
  tunnelUrl: string;
  desktopPublicKeyJwk: JsonWebKey;
  browserPublicKeyUploadUrl?: string;
  disconnectUrl?: string;
  loginUrl?: string;
  portalUrl?: string;
  portalRootUrl?: string;
  expiresAt?: string;
};

export type RemoteRpcRequest = {
  method: string;
  path: string;
  headers: Record<string, string>;
  bodyBase64: string | null;
};

type RemoteRpcResponse = {
  status: number;
  headers: Record<string, string>;
  bodyBase64: string | null;
};

export type RemoteEnvelope = {
  sessionId: string;
  keyId: string;
  nonce: string;
  timestamp: string;
  browserPublicKeyJwk?: JsonWebKey;
  ciphertext: string;
};

let remoteStatePromise: Promise<RemoteState> | null = null;

export class RemoteState {
  constructor(
    readonly handshake: RemoteHandshake,
    readonly key: CryptoKey,
    readonly keyId: string,
    readonly browserPublicKeyJwk: JsonWebKey,
  ) {}
}

class RemoteTunnelError extends Error {
  constructor(
    message: string,
    readonly status?: number,
    readonly loginUrl?: string,
    readonly portalUrl?: string,
    readonly portalRootUrl?: string,
  ) {
    super(message);
    this.name = "RemoteTunnelError";
  }
}

export function isForgerRemoteTunnel(): boolean {
  return REMOTE_FLAG;
}

export async function remoteFetch(input: RemoteRpcRequest, signal?: AbortSignal): Promise<Response> {
  return remoteFetchOnce(input, signal, true);
}

async function remoteFetchOnce(input: RemoteRpcRequest, signal: AbortSignal | undefined, allowTunnelAuthorization: boolean): Promise<Response> {
  const state = await getRemoteState().catch((error) => {
    showRemoteOverlay(error);
    throw error;
  });
  const envelope = await encryptRemoteEnvelope(state, input);
  const response = await fetch(`${state.handshake.tunnelUrl.replace(/\/+$/, "")}${REMOTE_RPC_PATH}`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "text/plain;charset=UTF-8",
    },
    body: JSON.stringify(envelope),
    signal,
  });
  if (allowTunnelAuthorization && response.status === 511 && await authorizeLocalTunnelReminder(state.handshake.tunnelUrl, response)) {
    return remoteFetchOnce(input, signal, false);
  }
  if (!response.ok) {
    return response;
  }
  const payload = await response.json().catch(() => null) as RemoteEnvelope | null;
  if (!payload?.ciphertext) {
    return new Response("remote_rpc_response_invalid", { status: 502 });
  }
  const decrypted = await decryptRemoteEnvelope<RemoteRpcResponse>(state, payload);
  return new Response(toArrayBuffer(base64ToBytes(decrypted.bodyBase64)), {
    status: decrypted.status,
    headers: decrypted.headers,
  });
}

export function mountForgerRemoteFab(): void {
  if (!isForgerRemoteTunnel() || typeof document === "undefined") {
    return;
  }
  void getRemoteState().then(() => clearRemoteOverlay()).catch((error) => showRemoteOverlay(error));
  if (document.getElementById("forger-remote-session-fab")) {
    return;
  }
  const button = document.createElement("button");
  button.id = "forger-remote-session-fab";
  button.type = "button";
  button.setAttribute("aria-label", "Forger Cloud");
  button.title = "Forger Cloud";
  button.innerHTML = FORGER_LOGO_SVG;
  Object.assign(button.style, {
    position: "fixed",
    right: "18px",
    bottom: "18px",
    zIndex: "2147483647",
    border: "0",
    borderRadius: "999px",
    width: "46px",
    height: "46px",
    padding: "0",
    background: "#0D1117",
    color: "#ffffff",
    display: "grid",
    placeItems: "center",
    boxShadow: "0 10px 28px rgba(17, 24, 39, 0.22)",
    cursor: "pointer",
  });
  button.addEventListener("click", () => toggleRemoteFabMenu(button));
  document.body.appendChild(button);
}

export async function disconnectRemoteSession(): Promise<void> {
  const state = await getRemoteState().catch(() => null);
  const url = state?.handshake.disconnectUrl;
  if (url) {
    await fetch(url, { method: "POST", credentials: "include" }).catch(() => undefined);
  }
  window.location.assign(state?.handshake.portalRootUrl || "/portal");
}

export async function getRemoteState(): Promise<RemoteState> {
  if (!REMOTE_FLAG) {
    throw new Error("forger_remote_tunnel_disabled");
  }
  if (!remoteStatePromise) {
    remoteStatePromise = createRemoteState();
  }
  return remoteStatePromise;
}

async function createRemoteState(): Promise<RemoteState> {
  if (!REMOTE_SESSION_ID || !REMOTE_HANDSHAKE_URL) {
    throw new RemoteTunnelError("forger_remote_handshake_missing");
  }
  const handshakeResponse = await fetch(REMOTE_HANDSHAKE_URL, {
    method: "GET",
    credentials: "include",
    headers: { Accept: "application/json" },
  });
  if (!handshakeResponse.ok) {
    const payload = await handshakeResponse.json().catch(() => null) as { loginUrl?: string; portalUrl?: string; portalRootUrl?: string } | null;
    throw new RemoteTunnelError(`forger_remote_handshake_failed_${handshakeResponse.status}`, handshakeResponse.status, payload?.loginUrl, payload?.portalUrl, payload?.portalRootUrl);
  }
  const handshake = await handshakeResponse.json() as RemoteHandshake;
  if (handshake.sessionId !== REMOTE_SESSION_ID || !handshake.tunnelUrl || !handshake.desktopPublicKeyJwk) {
    throw new RemoteTunnelError("forger_remote_handshake_invalid");
  }
  const browserPair = await crypto.subtle.generateKey(
    { name: "ECDH", namedCurve: "P-256" },
    true,
    ["deriveBits"],
  );
  const desktopPublicKey = await crypto.subtle.importKey(
    "jwk",
    handshake.desktopPublicKeyJwk,
    { name: "ECDH", namedCurve: "P-256" },
    false,
    [],
  );
  const sharedSecret = await crypto.subtle.deriveBits(
    { name: "ECDH", public: desktopPublicKey },
    browserPair.privateKey,
    256,
  );
  const keyMaterial = await crypto.subtle.digest("SHA-256", sharedSecret);
  const key = await crypto.subtle.importKey("raw", keyMaterial, { name: "AES-GCM" }, false, ["encrypt", "decrypt"]);
  const browserPublicKeyJwk = await crypto.subtle.exportKey("jwk", browserPair.publicKey);
  const keyId = await sha256Hex(JSON.stringify(browserPublicKeyJwk));
  if (handshake.browserPublicKeyUploadUrl) {
    await fetch(handshake.browserPublicKeyUploadUrl, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionId: REMOTE_SESSION_ID, browserPublicKeyJwk, keyId }),
    }).catch(() => undefined);
  }
  return new RemoteState(handshake, key, keyId, browserPublicKeyJwk);
}

export async function encryptRemoteEnvelope(state: RemoteState, payload: unknown): Promise<RemoteEnvelope> {
  const nonce = crypto.getRandomValues(new Uint8Array(12));
  const timestamp = new Date().toISOString();
  const plaintext = new TextEncoder().encode(JSON.stringify(payload));
  const ciphertext = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv: toArrayBuffer(nonce), additionalData: toArrayBuffer(aad(state.handshake.sessionId, state.keyId, timestamp)) },
    state.key,
    plaintext,
  );
  return {
    sessionId: state.handshake.sessionId,
    keyId: state.keyId,
    nonce: bytesToBase64(nonce),
    timestamp,
    browserPublicKeyJwk: state.browserPublicKeyJwk,
    ciphertext: bytesToBase64(new Uint8Array(ciphertext)),
  };
}

export async function decryptRemoteEnvelope<T>(state: RemoteState, envelope: RemoteEnvelope): Promise<T> {
  const plaintext = await crypto.subtle.decrypt(
    {
      name: "AES-GCM",
      iv: toArrayBuffer(base64ToBytes(envelope.nonce)),
      additionalData: toArrayBuffer(aad(envelope.sessionId, envelope.keyId, envelope.timestamp)),
    },
    state.key,
    toArrayBuffer(base64ToBytes(envelope.ciphertext)),
  );
  return JSON.parse(new TextDecoder().decode(plaintext)) as T;
}

function aad(sessionId: string, keyId: string, timestamp: string): Uint8Array {
  return new TextEncoder().encode(`${sessionId}\n${keyId}\n${timestamp}`);
}

function showRemoteOverlay(error: unknown): void {
  if (typeof document === "undefined") return;
  const remoteError = error instanceof RemoteTunnelError ? error : undefined;
  const loginUrl = remoteError?.loginUrl;
  const portalUrl = remoteError?.portalUrl;
  const portalRootUrl = remoteError?.portalRootUrl;
  const sessionEnded = remoteError?.status === 410;
  const title = sessionEnded
    ? "Sesión remota cerrada"
    : remoteError?.status === 401
      ? "Inicia sesión en Forger Cloud"
      : "Handshake remoto pendiente";
  const body = sessionEnded
    ? "Este túnel ya fue cerrado o expiró."
    : remoteError?.status === 401
      ? "Finance OS necesita confirmar tu sesión de Forger Cloud antes de conectarse con Desktop."
      : "No se pudo completar el handshake seguro con Forger Cloud.";
  renderRemoteOverlay({
    title,
    body,
    actionLabel: sessionEnded ? "Volver a Forger Cloud" : loginUrl ? "Iniciar sesión" : "Reintentar",
    action: () => {
      if (sessionEnded) {
        window.location.assign(portalRootUrl || "/portal");
        return;
      }
      if (loginUrl) {
        window.location.assign(loginUrl);
        return;
      }
      remoteStatePromise = null;
      void getRemoteState().then(() => clearRemoteOverlay()).catch((nextError) => showRemoteOverlay(nextError));
    },
    secondaryLabel: portalUrl ? "Ver en Forger Cloud" : undefined,
    secondaryAction: portalUrl ? () => window.location.assign(portalUrl) : undefined,
  });
}

function toggleRemoteFabMenu(anchor: HTMLElement): void {
  const existing = document.getElementById("forger-remote-session-menu");
  if (existing) {
    existing.remove();
    return;
  }
  const menu = document.createElement("div");
  menu.id = "forger-remote-session-menu";
  Object.assign(menu.style, {
    position: "fixed",
    right: "18px",
    bottom: "72px",
    zIndex: "2147483647",
    minWidth: "180px",
    padding: "6px",
    border: "1px solid rgba(255, 255, 255, 0.14)",
    borderRadius: "12px",
    background: "#111827",
    color: "#ffffff",
    boxShadow: "0 18px 44px rgba(17, 24, 39, 0.3)",
    font: "14px system-ui, -apple-system, BlinkMacSystemFont, sans-serif",
  });

  const disconnect = document.createElement("button");
  disconnect.type = "button";
  disconnect.textContent = "Desconectar";
  Object.assign(disconnect.style, {
    width: "100%",
    border: "0",
    borderRadius: "8px",
    padding: "10px 12px",
    background: "transparent",
    color: "#ffffff",
    textAlign: "left",
    font: "700 14px system-ui, -apple-system, BlinkMacSystemFont, sans-serif",
    cursor: "pointer",
  });
  disconnect.addEventListener("mouseenter", () => { disconnect.style.background = "rgba(255, 255, 255, 0.08)"; });
  disconnect.addEventListener("mouseleave", () => { disconnect.style.background = "transparent"; });
  disconnect.addEventListener("click", () => {
    menu.remove();
    void disconnectRemoteSession();
  });
  menu.appendChild(disconnect);
  document.body.appendChild(menu);

  const closeMenu = (event: MouseEvent) => {
    if (event.target instanceof Node && (menu.contains(event.target) || anchor.contains(event.target))) {
      return;
    }
    menu.remove();
    document.removeEventListener("mousedown", closeMenu);
  };
  setTimeout(() => document.addEventListener("mousedown", closeMenu), 0);
}

async function authorizeLocalTunnelReminder(tunnelUrl: string, response: Response): Promise<boolean> {
  const html = await response.text().catch(() => "");
  const continuePath = html.match(/url:\s*"([^"]*\/continue\/[^"]+)"/)?.[1];
  const endpoint = html.match(/<span id="endpoint-ip-text">([^<]+)<\/span>/)?.[1]?.trim();
  if (!continuePath || !endpoint) {
    return false;
  }
  const authorizeUrl = new URL(continuePath, tunnelUrl);
  const authorizeResponse = await fetch(authorizeUrl.toString(), {
    method: "POST",
    mode: "no-cors",
    credentials: "include",
    body: new URLSearchParams({ endpoint }),
  }).catch(() => null);
  return authorizeResponse !== null;
}

function clearRemoteOverlay(): void {
  document.getElementById("forger-remote-session-overlay")?.remove();
}

function renderRemoteOverlay(input: {
  title: string;
  body: string;
  actionLabel: string;
  action: () => void;
  secondaryLabel?: string;
  secondaryAction?: () => void;
}): void {
  clearRemoteOverlay();
  const overlay = document.createElement("div");
  overlay.id = "forger-remote-session-overlay";
  Object.assign(overlay.style, {
    position: "fixed",
    inset: "0",
    zIndex: "2147483646",
    display: "grid",
    placeItems: "center",
    padding: "24px",
    background: "rgba(6, 10, 14, 0.72)",
    backdropFilter: "blur(10px)",
  });

  const panel = document.createElement("div");
  Object.assign(panel.style, {
    width: "min(100%, 420px)",
    border: "1px solid rgba(255, 255, 255, 0.16)",
    borderRadius: "16px",
    padding: "24px",
    background: "#121820",
    color: "#f8fafc",
    boxShadow: "0 24px 70px rgba(0, 0, 0, 0.38)",
    font: "14px system-ui, -apple-system, BlinkMacSystemFont, sans-serif",
  });

  const title = document.createElement("h2");
  title.textContent = input.title;
  Object.assign(title.style, { margin: "0 0 10px", fontSize: "20px", lineHeight: "1.2" });

  const body = document.createElement("p");
  body.textContent = input.body;
  Object.assign(body.style, { margin: "0 0 20px", color: "#b6c2cf", lineHeight: "1.5" });

  const actions = document.createElement("div");
  Object.assign(actions.style, { display: "flex", gap: "10px", flexWrap: "wrap" });

  const primary = document.createElement("button");
  primary.type = "button";
  primary.textContent = input.actionLabel;
  primary.addEventListener("click", input.action);
  Object.assign(primary.style, buttonStyle("#8db4e2", "#08111c"));
  actions.appendChild(primary);

  if (input.secondaryLabel && input.secondaryAction) {
    const secondary = document.createElement("button");
    secondary.type = "button";
    secondary.textContent = input.secondaryLabel;
    secondary.addEventListener("click", input.secondaryAction);
    Object.assign(secondary.style, buttonStyle("#1e2937", "#e2e8f0"));
    actions.appendChild(secondary);
  }

  panel.append(title, body, actions);
  overlay.appendChild(panel);
  document.body.appendChild(overlay);
}

function buttonStyle(background: string, color: string): Partial<CSSStyleDeclaration> {
  return {
    border: "0",
    borderRadius: "999px",
    padding: "10px 14px",
    background,
    color,
    font: "700 13px system-ui, -apple-system, BlinkMacSystemFont, sans-serif",
    cursor: "pointer",
  };
}

async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest)).map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return btoa(binary);
}

export function base64ToBytes(value: string | null): Uint8Array {
  if (!value) return new Uint8Array();
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

function toArrayBuffer(bytes: Uint8Array): ArrayBuffer {
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
}
