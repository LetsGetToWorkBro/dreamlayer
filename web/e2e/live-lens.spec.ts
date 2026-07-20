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
    expect(csp).toMatch(/script-src 'nonce-/);
    expect(csp).not.toContain("'unsafe-inline'");

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

  // The AAA overhaul: continuous ambient recognition, the rich panel, the live
  // toggle, and tap-to-escalate — all driven by a real browser with the look
  // route mocked so a labelled result renders deterministically.
  test("runs the continuous ambient loop, renders the panel, and escalates on tap", async ({ page }) => {
    const looks: { ambient: boolean }[] = [];
    await page.route("**/dreamlayer/live/look**", async (route) => {
      looks.push({ ambient: /[?&]ambient=1/.test(route.request().url()) });
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ok: true, label: "coffee mug", confidence: 0.91, tier: "laptop",
          lines: ["coffee mug · 91%"],
          panel: {
            type: "ObjectPanelCard", primary: "coffee mug", label: "coffee mug",
            confidence: 0.91, rows: [{ label: "$4.50 → $4.95", source: "currency" }],
            sources: ["currency"], footer: "91% · on-device",
          },
        }),
      });
    });

    const pageErrors: string[] = [];
    page.on("pageerror", (e) => pageErrors.push(String(e)));
    await page.goto("/dreamlayer/live", { waitUntil: "networkidle" });

    // live mode is the default (glasses never wait for a tap)
    await expect(page.locator("#livebtn")).toHaveAttribute("aria-checked", "true");
    await expect(page.locator("#livest")).toHaveText("live");

    // 1. the loop auto-fires WITHOUT any tap, and those frames carry ambient=1
    await expect.poll(() => looks.length, { timeout: 10_000 }).toBeGreaterThan(0);
    expect(looks.some((l) => l.ambient)).toBe(true);

    // 2. a labelled result paints the HUD and the rich provider panel
    await expect(page.locator("#hud")).toContainText("coffee mug");
    await expect(page.locator("#panel")).toHaveClass(/on/);
    await expect(page.locator("#panel")).toContainText("coffee mug");
    await expect(page.locator("#panel")).toContainText("$4.95");
    await expect(page.locator("#panel")).toContainText("currency");

    // 3. a deliberate tap escalates — a look WITHOUT the ambient flag
    const before = looks.length;
    await page.locator("#lens").click();
    await expect.poll(() => looks.length, { timeout: 6_000 }).toBeGreaterThan(before);
    expect(looks.some((l) => !l.ambient)).toBe(true);

    // 4. turning live OFF stops the loop (no new looks after a quiet period)
    await page.locator("#livebtn").click();
    await expect(page.locator("#livest")).toHaveText("tap");
    const frozen = looks.length;
    await page.waitForTimeout(3_000);
    expect(looks.length).toBe(frozen);

    expect(pageErrors, `page threw:\n${pageErrors.join("\n")}`).toEqual([]);
  });

  // Refute 2026-07-20: an unpaired phone (401) must PAUSE the continuous loop
  // behind the pairing modal, not keep capturing + POSTing frames every tick.
  test("pauses the continuous loop while unpaired (401), not burning frames", async ({ page }) => {
    let looks = 0;
    await page.route("**/dreamlayer/live/look**", async (route) => {
      looks++;
      await route.fulfill({ status: 401, contentType: "application/json", body: "{}" });
    });
    // the boot status check also 401s → the page should show the pairing modal
    await page.route("**/dreamlayer/status**", async (route) => {
      await route.fulfill({ status: 401, contentType: "application/json", body: "{}" });
    });

    await page.goto("/dreamlayer/live", { waitUntil: "networkidle" });

    // the pairing modal appears (not a silent dark screen)
    await expect(page.locator(".notice")).toContainText("CONNECT THIS PHONE");

    // and the loop stays paused — no look frames are captured/POSTed while unpaired
    await page.waitForTimeout(3_000);
    expect(looks).toBe(0);
  });
});
