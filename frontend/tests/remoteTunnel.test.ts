import { afterEach, describe, expect, it, vi } from "vitest";

async function importRemoteTunnel() {
  vi.resetModules();
  vi.stubEnv("VITE_FORGER_REMOTE_TUNNEL", "true");
  vi.stubEnv("VITE_FORGER_REMOTE_SESSION_ID", "remote-finance-os");
  vi.stubEnv("VITE_FORGER_CLOUD_HANDSHAKE_URL", "/remote-assets/remote-finance-os/handshake");
  return import("../remoteTunnel");
}

afterEach(() => {
  vi.resetModules();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("remote tunnel mobile access grant", () => {
  it("reads the mobile access token from the URL fragment and clears the visible URL", async () => {
    const replaceState = vi.fn();
    vi.stubGlobal("document", { title: "Finance OS" });
    vi.stubGlobal("window", {
      location: {
        hash: "#forgerMobileAccessToken=mobile-grant&tab=overview",
        pathname: "/remote-assets/remote-finance-os/",
        search: "?view=app",
      },
      history: {
        state: { current: true },
        replaceState,
      },
    });
    vi.stubGlobal("localStorage", new Proxy({}, {
      get() {
        throw new Error("localStorage must not be used for remote mobile grants");
      },
    }));
    vi.stubGlobal("sessionStorage", new Proxy({}, {
      get() {
        throw new Error("sessionStorage must not be used for remote mobile grants");
      },
    }));

    const { remoteAssetHeaders, remoteMobileAccessToken } = await importRemoteTunnel();

    expect(remoteMobileAccessToken()).toBe("mobile-grant");
    expect(remoteAssetHeaders({ Accept: "application/json" })).toEqual({
      Accept: "application/json",
      Authorization: "Bearer mobile-grant",
    });
    expect(replaceState).toHaveBeenCalledWith(
      { current: true },
      "Finance OS",
      "/remote-assets/remote-finance-os/?view=app#tab=overview",
    );
  });

  it("keeps cookie-only Portal access when no mobile token exists", async () => {
    vi.stubGlobal("document", { title: "Finance OS" });
    vi.stubGlobal("window", {
      location: {
        hash: "",
        pathname: "/remote-assets/remote-finance-os/",
        search: "",
      },
      history: {
        state: null,
        replaceState: vi.fn(),
      },
    });

    const { remoteAssetHeaders, remoteMobileAccessToken } = await importRemoteTunnel();

    expect(remoteMobileAccessToken()).toBeUndefined();
    expect(remoteAssetHeaders({ Accept: "application/json" })).toEqual({ Accept: "application/json" });
  });
});
