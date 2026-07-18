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
});
