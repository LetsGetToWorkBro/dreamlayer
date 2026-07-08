/**
 * i18n — the app follows the device language (set once at launch). English is
 * the fallback for any locale or key we don't have. `t("now.ask")` reads the
 * catalog in src/i18n/translations.ts.
 *
 * CJK note: RN text uses Space Grotesk (Latin-only); iOS substitutes the system
 * font per-glyph for Japanese/Korean/Chinese, so those render on device.
 */
import { I18n } from "i18n-js";
import { getLocales } from "expo-localization";
import { translations } from "./translations";

const i18n = new I18n(translations);
i18n.enableFallback = true;
i18n.defaultLocale = "en";

// expo-localization reports a 2-letter languageCode (e.g. "en", "pt", "zh"),
// which matches our catalog keys; fall back to English otherwise.
const device = getLocales()?.[0]?.languageCode ?? "en";
i18n.locale = device in translations ? device : "en";

export function t(key: string, options?: object): string {
  return i18n.t(key, options);
}

/** The resolved locale actually in use (after fallback). */
export const locale = i18n.locale;
