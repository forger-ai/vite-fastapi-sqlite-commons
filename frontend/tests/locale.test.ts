import { afterEach, describe, expect, it, vi } from "vitest";
import { jsonResponse } from "../testing/fetchMock";
import {
  initialLocale,
  loadForgerRuntimeContext,
  localeFromNavigator,
  localeFromSearch,
  normalizeLocale,
} from "../locale";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("commons frontend locale", () => {
  it("normalizes supported Forger locales", () => {
    expect(normalizeLocale("en")).toBe("en");
    expect(normalizeLocale("en-US")).toBe("en");
    expect(normalizeLocale("es-CL")).toBe("es");
    expect(normalizeLocale(null)).toBe("es");
  });

  it("resolves URL locale with Forger priority and legacy fallback", () => {
    expect(localeFromSearch("?forgerLocale=en-US&locale=es")).toBe("en");
    expect(localeFromSearch("?locale=en-GB")).toBe("en");
    expect(localeFromSearch("")).toBeNull();
  });

  it("resolves navigator locale from language preferences", () => {
    vi.stubGlobal("navigator", undefined);
    expect(localeFromNavigator()).toBeNull();
    vi.unstubAllGlobals();
    expect(localeFromNavigator({ languages: ["fr-CA", "en-US"], language: "es-CL" })).toBe("en");
    expect(localeFromNavigator({ languages: [], language: "en-AU" })).toBe("en");
    expect(localeFromNavigator({ languages: [], language: "" })).toBeNull();
  });

  it("uses URL, navigator, then fallback for initial locale", () => {
    expect(initialLocale({
      search: "?forgerLocale=es-CL",
      navigator: { languages: ["en-US"], language: "en-US" },
    })).toBe("es");
    expect(initialLocale({
      search: "",
      navigator: { languages: ["en-US"], language: "en-US" },
    })).toBe("en");
    expect(initialLocale({ search: "", navigator: { languages: [], language: "" }, fallback: "en" })).toBe("en");
    expect(initialLocale({ search: "", navigator: { languages: [], language: "" } })).toBe("es");
  });

  it("loads and normalizes Forger runtime context from the app backend", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse({
      locale: "fr-CA",
      rawLocale: "en-GB",
      source: "desktop",
    }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(loadForgerRuntimeContext()).resolves.toEqual({
      locale: "es",
      rawLocale: "en-GB",
      source: "desktop",
    });
  });

  it("treats unknown runtime context sources as fallback", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse({
      rawLocale: "",
      source: "other",
    }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(loadForgerRuntimeContext()).resolves.toEqual({
      locale: "es",
      rawLocale: null,
      source: "fallback",
    });
  });
});
