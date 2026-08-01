/**
 * Every screen in `app/` is registered, and every registered screen can be got
 * to.
 *
 * This is the phone's version of the check `scripts/lens_reachability.py` does
 * for the Brain, and it exists for the same reason that one does: a file that
 * imports cleanly, typechecks and renders perfectly is still not a feature if
 * nothing routes to it. expo-router will happily serve an unregistered file at
 * its path AND surface it as a tab, so a new screen that nobody declares
 * either appears in the tab bar by accident or is reachable only by someone
 * typing the URL — and neither is what was intended.
 *
 * Two claims, both about the same gap:
 *   1. every `app/*.tsx` appears in `_layout.tsx`, as a tab or `href: null`;
 *   2. every `href: null` screen is pushed from somewhere the wearer can tap.
 */
import fs from "fs";
import path from "path";

const APP = path.resolve(__dirname, "..", "..", "app");
const layout = fs.readFileSync(path.join(APP, "_layout.tsx"), "utf8");

/** Screen files, by route name. `index` and `_layout` are expo-router's own. */
const screens = fs
  .readdirSync(APP)
  .filter((f) => f.endsWith(".tsx") && f !== "_layout.tsx")
  .map((f) => f.replace(/\.tsx$/, ""));

/** `<Tabs.Screen name="x"` — every declaration, tab or hidden. */
const declared = new Set(
  [...layout.matchAll(/<Tabs\.Screen\s+name="([^"]+)"/g)].map((m) => m[1]),
);

/** …of those, the ones explicitly hidden from the tab bar. */
const hidden = new Set(
  [...layout.matchAll(/<Tabs\.Screen\s+name="([^"]+)"[^>]*href:\s*null/g)].map((m) => m[1]),
);

/** Every route string anything pushes or lists, across the whole app. */
const pushed = (() => {
  const out = new Set<string>();
  const walk = (dir: string) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name);
      if (e.isDirectory()) {
        if (e.name !== "node_modules" && e.name !== "__tests__") walk(p);
        continue;
      }
      if (!/\.tsx?$/.test(e.name)) continue;
      const src = fs.readFileSync(p, "utf8");
      for (const m of src.matchAll(/["'`]\/([a-z0-9-]+)["'`]/g)) out.add(String(m[1]));
    }
  };
  walk(APP);
  walk(path.resolve(__dirname, "..", "..", "src"));
  return out;
})();

describe("every screen is declared", () => {
  it("finds the screens at all (the scan is not vacuous)", () => {
    expect(screens.length).toBeGreaterThan(20);
    expect(screens).toContain("listening");
  });

  it.each(screens)("app/%s.tsx is registered in _layout.tsx", (name) => {
    expect(declared.has(name)).toBe(true);
  });

  it("declares nothing that does not exist", () => {
    const ghosts = [...declared].filter((d) => !screens.includes(String(d)));
    expect(ghosts).toEqual([]);
  });
});

describe("every hidden screen can be reached by tapping", () => {
  it("has hidden screens to check", () => {
    expect(hidden.size).toBeGreaterThan(10);
  });

  it.each([...hidden].filter((h) => h !== "index"))(
    "/%s is pushed from somewhere",
    (name) => {
      // `index` is the router's entry point and is reached by launching the
      // app, not by a push — the only exemption, and it is named rather than
      // pattern-matched so a second one cannot slip in silently.
      expect(pushed.has(String(name))).toBe(true);
    },
  );
});
