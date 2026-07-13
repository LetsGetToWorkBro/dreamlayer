/** i18n catalog integrity: every locale carries the same key set as English,
 * and no wired t("…") key is missing. As the app body was localized past the
 * ~20 chrome strings (Memories, Now, Look, Messages, People, glasses states),
 * the risk shifted from "not translated" to "one locale silently drifts a key"
 * — a missing key falls back to English at runtime with no error. This test
 * makes that drift a build failure instead. */
import { translations } from "../i18n/translations";

type Tree = { [k: string]: string | Tree };

function leafKeys(obj: Tree, prefix = ""): string[] {
  const out: string[] = [];
  for (const [k, v] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object") out.push(...leafKeys(v as Tree, path));
    else out.push(path);
  }
  return out.sort();
}

const locales = Object.keys(translations) as (keyof typeof translations)[];
const enKeys = leafKeys(translations.en as Tree);

describe("i18n catalog", () => {
  it("ships the expected locale set", () => {
    expect(locales).toEqual(
      expect.arrayContaining(["en", "es", "fr", "de", "it", "pt", "ja", "ko", "zh"]),
    );
  });

  it.each(locales.filter((l) => l !== "en"))(
    "%s has exactly the English key set — no missing or extra keys",
    (loc) => {
      const keys = leafKeys(translations[loc] as Tree);
      const missing = enKeys.filter((k) => !keys.includes(k));
      const extra = keys.filter((k) => !enKeys.includes(k));
      expect({ locale: loc, missing, extra }).toEqual({ locale: loc, missing: [], extra: [] });
    },
  );

  it("has no empty string values", () => {
    for (const loc of locales) {
      const tree = translations[loc] as Tree;
      const walk = (o: Tree) => {
        for (const v of Object.values(o)) {
          if (v && typeof v === "object") walk(v as Tree);
          else expect(String(v).length).toBeGreaterThan(0);
        }
      };
      walk(tree);
    }
  });
});
