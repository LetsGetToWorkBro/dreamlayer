import { test, expect, type Page } from "@playwright/test";
import fs from "node:fs";

const SHOTS = "e2e/shots";
fs.mkdirSync(SHOTS, { recursive: true });

// Scroll so that a pinned act sits at `progress` (0..1) through its pin, or an
// unpinned section sits near the top of the viewport, then let the scrub settle.
async function scrollToSection(page: Page, selector: string, progress = 0.5): Promise<void> {
  await page.evaluate(
    ([sel, prog]) => {
      const el = document.querySelector(sel as string)!;
      const spacer = el.closest(".pin-spacer") ?? el;
      const rect = spacer.getBoundingClientRect();
      const top = rect.top + window.scrollY;
      const travel = Math.max(0, rect.height - window.innerHeight);
      const y = top + travel * (prog as number);
      const lenis = (window as unknown as { __lenis?: { scrollTo: (v: number, o: object) => void } }).__lenis;
      if (lenis) lenis.scrollTo(y, { immediate: true, force: true });
      else window.scrollTo(0, y);
    },
    [selector, progress] as const
  );
  await page.waitForTimeout(1200); // scrub + arrival animations settle
}

async function shoot(page: Page, name: string): Promise<void> {
  await page.screenshot({ path: `${SHOTS}/${name}.png` });
}

test.describe("landing page", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    if (testInfo.project.name === "reduced") {
      await page.emulateMedia({ reducedMotion: "reduce" });
    }
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(1500); // hero entrance
  });

  test("no horizontal overflow", async ({ page }) => {
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test("scenes and sections render", async ({ page }, testInfo) => {
    const p = testInfo.project.name;
    await shoot(page, `${p}-01-hero`);

    if (p === "reduced") {
      // Static contract: no pin spacers, hold beats visible, full page capture.
      expect(await page.locator(".pin-spacer").count()).toBe(0);
      await expect(page.locator("#act-veritas .beat-hold")).toBeVisible();
      await scrollToSection(page, "#act-veritas");
      await shoot(page, `${p}-02-veritas-static`);
      await scrollToSection(page, ".privacy");
      await shoot(page, `${p}-03-privacy`);
      return;
    }

    // Motion contract: acts are pinned and the real overlays land mid-scene.
    await expect(page.locator(".pin-spacer").first()).toBeAttached();

    await scrollToSection(page, "#act-veritas", 0.75);
    await expect(page.locator("#act-veritas .beat").nth(3)).toBeVisible();
    await shoot(page, `${p}-02-veritas`);

    await scrollToSection(page, "#act-answer", 0.6);
    await shoot(page, `${p}-03-answer-ahead`);

    await scrollToSection(page, "#act-memory", 0.55);
    await shoot(page, `${p}-04-memory`);

    await scrollToSection(page, "#act-juno", 0.7);
    await shoot(page, `${p}-05-juno`);

    await scrollToSection(page, ".catalog", 0.2);
    await shoot(page, `${p}-06-catalog`);

    await scrollToSection(page, ".privacy");
    await shoot(page, `${p}-07-privacy`);

    await scrollToSection(page, ".close");
    await shoot(page, `${p}-08-close`);
  });

  test("waitlist CTA is a mailto by default", async ({ page }) => {
    const href = await page.locator("[data-waitlist] a").getAttribute("href");
    expect(href).toContain("mailto:info@labyrinth.vision");
  });
});
