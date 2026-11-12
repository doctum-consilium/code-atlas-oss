import { describe, expect, it, vi } from "vitest";

import {
  detectLanguage,
  dictionaries,
  getLanguage,
  setLanguage,
  subscribeLanguage,
  t,
  tn,
  translate,
} from "../src/i18n";

describe("i18n", () => {
  it("has the same keys in both languages, none empty", () => {
    expect(Object.keys(dictionaries.fr).sort()).toEqual(Object.keys(dictionaries.en).sort());
    for (const language of ["en", "fr"] as const) {
      for (const text of Object.values(dictionaries[language])) expect(text.trim()).not.toBe("");
    }
  });

  it("detects the browser language, English by default", () => {
    expect(detectLanguage("fr-FR")).toBe("fr");
    expect(detectLanguage("FR")).toBe("fr");
    expect(detectLanguage("de-DE")).toBe("en");
    expect(detectLanguage(undefined)).toBe("en");
  });

  it("fills placeholders and leaves unknown ones", () => {
    expect(translate("en", "error.status", { status: 502 })).toBe("Error 502");
    expect(translate("fr", "error.status", { status: 502 })).toBe("Erreur 502");
    expect(translate("en", "error.status")).toBe("Error {status}");
    expect(translate("en", "error.status", { other: 1 })).toBe("Error {status}");
  });

  it("switches language, notifies listeners, and picks plural forms", () => {
    const listener = vi.fn();
    const stop = subscribeLanguage(listener);
    expect(getLanguage()).toBe("en");
    expect(tn("search.count", 1, { ms: 5 })).toBe("1 result in 5 ms");
    expect(tn("search.count", 0, { ms: 5 })).toBe("0 results in 5 ms");
    setLanguage("fr");
    setLanguage("fr");
    expect(listener).toHaveBeenCalledTimes(1);
    expect(t("nav.repos")).toBe("Dépôts");
    expect(tn("search.count", 0, { ms: 5 })).toBe("0 passage en 5 ms");
    expect(tn("search.count", 3, { ms: 5 })).toBe("3 passages en 5 ms");
    stop();
    setLanguage("en");
    expect(listener).toHaveBeenCalledTimes(1);
  });
});
