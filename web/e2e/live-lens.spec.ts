import { test, expect, type ConsoleMessage } from "@playwright/test";

// Boots the Brain-served Live Lens page in a real Chromium with a fake camera
// and proves the browser HALF works — the part the Python unit tests can't see:
//  1. the strict nonce CSP lets the page's own inline <script>/<style> run
//     (a CSP regression that blocked them shows up as a console violation);
//  2. the page is a secure context (127.0.0.1) so getUserMedia is allowed;
//  3. the lens renders and the Veil toggle actually flips;
//  4. the camera path succeeds (no "needs a secure page / no camera" notice).

test.describe("Live Lens page in a real browser", () => {
  test("boots under the CSP, opens the fake camera, and toggles the Veil", async ({ page }) => {
    const cspErrors: string[] = [];
    page.on("console", (m: ConsoleMessage) => {
      const t = m.text();
      if (/content security policy|csp|refused to (execute|load|apply|connect)/i.test(t)) {
        cspErrors.push(t);
      }
    });
    const pageErrors: string[] = [];
    page.on("pageerror", (e) => pageErrors.push(String(e)));

    await page.goto("/dreamlayer/live", { waitUntil: "networkidle" });

    // 1. the inline script ran under the CSP — no violation, no uncaught error
    expect(cspErrors, `CSP blocked the page:\n${cspErrors.join("\n")}`).toEqual([]);
    expect(pageErrors, `page threw:\n${pageErrors.join("\n")}`).toEqual([]);

    // the CSP header itself is nonce-based, not unsafe-inline
    const resp = await page.request.get("/dreamlayer/live");
    const csp = resp.headers()["content-security-policy"] ?? "";
    const scriptDir = csp.split(";").find((d) => d.includes("script-src")) ?? "";
    expect(scriptDir).toMatch(/'nonce-/);              // still nonce-based
    expect(csp).not.toContain("'unsafe-inline'");
    expect(scriptDir).not.toContain("'unsafe-eval'");  // wasm-unsafe-eval only, not full eval

    // 2. secure context (loopback) → getUserMedia is permitted
    expect(await page.evaluate(() => window.isSecureContext)).toBe(true);

    // 3. the lens + veil chrome rendered; the toggle flips
    await expect(page.locator("#lens")).toBeVisible();
    const veil = page.locator("#veilbtn");
    await expect(veil).toHaveAttribute("aria-checked", "false");
    await veil.click();
    await expect(veil).toHaveAttribute("aria-checked", "true");
    await expect(page.locator("#veilst")).toHaveText("on");

    // 4. the camera path succeeded — the fake device attached a live stream and
    // the "no camera / needs a secure page" notice never appeared.
    await expect
      .poll(() => page.evaluate(() => {
        const v = document.querySelector<HTMLVideoElement>("#cam");
        return v && v.srcObject ? v.videoWidth : 0;
      }), { timeout: 15_000 })
      .toBeGreaterThan(0);
    await expect(page.locator(".notice")).toHaveCount(0);
  });

  // Phase 4: the vendored on-device detector loads under the (relaxed) live-page
  // CSP in a REAL browser — 14 MB of MediaPipe module + WASM + int8 model, all
  // same-origin — and takes over recognition so the Brain ambient loop idles. A
  // deliberate tap still escalates to the Brain for the rich panel.
  const CANNED_LOOK = {
    ok: true, label: "coffee mug", confidence: 0.91, tier: "laptop",
    lines: ["coffee mug · 91%"],
    panel: {
      type: "ObjectPanelCard", primary: "coffee mug", label: "coffee mug",
      confidence: 0.91, rows: [{ label: "$4.50 → $4.95", source: "currency" }],
      sources: ["currency"], footer: "91% · on-device",
    },
  };

  test("loads the on-device detector under the CSP and idles the server loop", async ({ page }) => {
    const csp: string[] = [];
    const pageErrors: string[] = [];
    page.on("console", (m) => {
      if (/content security|csp|refused to (execute|load|compile|connect)/i.test(m.text())) csp.push(m.text());
    });
    page.on("pageerror", (e) => pageErrors.push(String(e)));

    const looks: { ambient: boolean }[] = [];
    await page.route("**/dreamlayer/live/look**", async (route) => {
      looks.push({ ambient: /[?&]ambient=1/.test(route.request().url()) });
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(CANNED_LOOK) });
    });

    await page.goto("/dreamlayer/live", { waitUntil: "networkidle" });

    // the detector loads (module -> WASM -> model) under the strict CSP
    await expect(page.locator("body")).toHaveAttribute("data-detector", "on", { timeout: 40_000 });
    expect(csp, `CSP blocked the detector:\n${csp.join("\n")}`).toEqual([]);

    // the browser recognizes now, so the Brain AMBIENT loop stays idle
    await page.waitForTimeout(2_500);
    expect(looks.filter((l) => l.ambient).length).toBe(0);

    // a deliberate tap STILL escalates to the Brain and renders the rich panel
    await page.locator("#lens").click();
    await expect.poll(() => looks.filter((l) => !l.ambient).length, { timeout: 6_000 }).toBeGreaterThan(0);
    await expect(page.locator("#panel")).toHaveClass(/on/);
    await expect(page.locator("#panel")).toContainText("$4.95");

    expect(pageErrors, `page threw:\n${pageErrors.join("\n")}`).toEqual([]);
  });

  // Graceful degradation: if the detector assets can't load (old device / blocked),
  // the Brain ambient loop takes over so recognition still works.
  test("falls back to the Brain ambient loop when the detector can't load", async ({ page }) => {
    await page.route("**/dreamlayer/live/assets/**", (route) => route.fulfill({ status: 404, body: "" }));
    const looks: { ambient: boolean }[] = [];
    await page.route("**/dreamlayer/live/look**", async (route) => {
      looks.push({ ambient: /[?&]ambient=1/.test(route.request().url()) });
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(CANNED_LOOK) });
    });

    await page.goto("/dreamlayer/live", { waitUntil: "networkidle" });

    // the detector reports it couldn't load...
    await expect(page.locator("body")).toHaveAttribute("data-detector", "off", { timeout: 20_000 });
    // ...and the Brain ambient loop takes over (frames carry ambient=1)
    await expect.poll(() => looks.filter((l) => l.ambient).length, { timeout: 10_000 }).toBeGreaterThan(0);
    await expect(page.locator("#panel")).toContainText("$4.95");
  });

  // Refute 2026-07-20: an unpaired phone (401) must PAUSE the fallback ambient
  // loop behind the pairing modal, not keep capturing + POSTing frames. (Force
  // the fallback path by blocking the detector assets so the server loop is live.)
  test("pauses the fallback ambient loop while unpaired (401), not burning frames", async ({ page }) => {
    await page.route("**/dreamlayer/live/assets/**", (route) => route.fulfill({ status: 404, body: "" }));
    let looks = 0;
    await page.route("**/dreamlayer/live/look**", async (route) => {
      looks++;
      await route.fulfill({ status: 401, contentType: "application/json", body: "{}" });
    });
    await page.route("**/dreamlayer/status**", (route) =>
      route.fulfill({ status: 401, contentType: "application/json", body: "{}" }));

    await page.goto("/dreamlayer/live", { waitUntil: "networkidle" });

    // the pairing modal appears (not a silent dark screen)
    await expect(page.locator(".notice")).toContainText("CONNECT THIS PHONE");
    // and the loop stays paused — no look frames POSTed while unpaired
    await page.waitForTimeout(3_000);
    expect(looks).toBe(0);
  });
});
