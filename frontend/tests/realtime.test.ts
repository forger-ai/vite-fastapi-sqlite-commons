import { afterEach, describe, expect, it, vi } from "vitest";

class FakeWebSocket extends EventTarget {
  static instances: FakeWebSocket[] = [];
  static OPEN = 1;
  static CONNECTING = 0;
  static CLOSED = 3;

  readyState = FakeWebSocket.CONNECTING;
  sent: string[] = [];

  constructor(readonly url: string) {
    super();
    FakeWebSocket.instances.push(this);
  }

  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.dispatchEvent(new Event("open"));
  }

  receive(data: string) {
    this.dispatchEvent(new MessageEvent("message", { data }));
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {
    this.readyState = FakeWebSocket.CLOSED;
    this.dispatchEvent(new Event("close"));
  }
}

async function importRealtime(baseUrl = "http://api.test") {
  vi.resetModules();
  vi.stubEnv("VITE_API_BASE_URL", baseUrl);
  vi.stubGlobal("WebSocket", FakeWebSocket);
  FakeWebSocket.instances = [];
  return import("../realtime");
}

afterEach(() => {
  vi.resetModules();
  vi.doUnmock("../remoteTunnel");
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("realtime client", () => {
  it("connects locally and sends subscribe messages to the stack realtime endpoint", async () => {
    const { createRealtimeClient } = await importRealtime("https://api.test///");
    const client = createRealtimeClient();
    const connected = client.connect();
    await vi.waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    FakeWebSocket.instances[0].open();
    await connected;

    await client.subscribe("status");

    expect(FakeWebSocket.instances[0].url).toBe("wss://api.test/api/realtime/ws");
    expect(FakeWebSocket.instances[0].sent).toEqual([JSON.stringify({ action: "subscribe", channel: "status" })]);
  });

  it("uses encrypted remote websocket envelopes and decrypts remote events", async () => {
    vi.doMock("../remoteTunnel", () => ({
      REMOTE_WS_PATH: "/__forger_remote_ws",
      isForgerRemoteTunnel: () => true,
      getRemoteState: vi.fn(async () => ({ handshake: { tunnelUrl: "https://session.loca.lt" } })),
      encryptRemoteEnvelope: vi.fn(async (_state: unknown, payload: unknown) => ({ ciphertext: JSON.stringify(payload) })),
      decryptRemoteEnvelope: vi.fn(async (_state: unknown, envelope: { event: unknown }) => envelope.event),
    }));
    const { createRealtimeClient } = await importRealtime("http://api.test");
    const client = createRealtimeClient();
    const events: unknown[] = [];
    client.onEvent((event) => events.push(event));

    const connected = client.connect();
    await vi.waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    FakeWebSocket.instances[0].open();
    await connected;
    await client.subscribe("status");
    FakeWebSocket.instances[0].receive(JSON.stringify({ event: { channel: "status", type: "updated" } }));
    await vi.waitFor(() => expect(events.length).toBe(1));

    expect(FakeWebSocket.instances[0].url).toBe("wss://session.loca.lt/__forger_remote_ws");
    expect(FakeWebSocket.instances[0].sent).toEqual([
      JSON.stringify({ ciphertext: JSON.stringify({ action: "subscribe", channel: "status" }) }),
    ]);
    expect(events).toEqual([{ channel: "status", type: "updated" }]);
  });
});
