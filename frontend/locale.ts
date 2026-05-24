import { get } from "./client";

export type Locale = "es" | "en";
export type ForgerContextSource = "desktop" | "fallback";

export interface ForgerRuntimeContext {
  locale: Locale;
  rawLocale: string | null;
  source: ForgerContextSource;
}

export const defaultLocale: Locale = "es";

export function normalizeLocale(value: string | null | undefined): Locale {
  const normalized = (value ?? "").trim().toLowerCase();
  return normalized === "en" || normalized.startsWith("en-") ? "en" : "es";
}

export function localeFromSearch(search: string | undefined = globalThis.location?.search): Locale | null {
  if (!search) {
    return null;
  }
  const params = new URLSearchParams(search);
  const forgerLocale = params.get("forgerLocale");
  if (forgerLocale) {
    return normalizeLocale(forgerLocale);
  }
  const legacyLocale = params.get("locale");
  return legacyLocale ? normalizeLocale(legacyLocale) : null;
}

export function localeFromNavigator(nav: Pick<Navigator, "language" | "languages"> | undefined = globalThis.navigator): Locale | null {
  if (!nav) {
    return null;
  }
  for (const language of nav.languages ?? []) {
    if (normalizeLocale(language) === "en") {
      return "en";
    }
  }
  return nav.language ? normalizeLocale(nav.language) : null;
}

export function initialLocale(options: {
  search?: string;
  navigator?: Pick<Navigator, "language" | "languages">;
  fallback?: Locale;
} = {}): Locale {
  return (
    localeFromSearch(options.search)
    ?? localeFromNavigator(options.navigator)
    ?? options.fallback
    ?? defaultLocale
  );
}

export async function loadForgerRuntimeContext(signal?: AbortSignal): Promise<ForgerRuntimeContext> {
  const context = await get<Partial<ForgerRuntimeContext>>("/api/forger/context", signal);
  return {
    locale: normalizeLocale(context.locale ?? context.rawLocale),
    rawLocale: typeof context.rawLocale === "string" && context.rawLocale ? context.rawLocale : null,
    source: context.source === "desktop" ? "desktop" : "fallback",
  };
}
