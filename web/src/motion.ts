import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import Lenis from "lenis";
import { loadManifest } from "./lib/manifest";
import { buildAct, type ActMode } from "./lib/scene-player";

// One motion vocabulary for everything that merely appears (vs. the acts,
// which replay the renderer's own edit): arrive from 14px below, signature
// deceleration, never pop.
const ARRIVE = { y: 14, opacity: 0 };
const ARRIVED = { y: 0, opacity: 1, duration: 0.7, ease: "expo.out" };

function smoothScroll(): Lenis {
  const lenis = new Lenis({ lerp: 0.12 });
  lenis.on("scroll", ScrollTrigger.update);
  gsap.ticker.add((time) => lenis.raf(time * 1000));
  gsap.ticker.lagSmoothing(0);
  (window as unknown as { __lenis: Lenis }).__lenis = lenis; // test hook

  document.querySelectorAll<HTMLAnchorElement>('a[href^="#"]').forEach((a) => {
    a.addEventListener("click", (e) => {
      const target = a.getAttribute("href")!;
      if (target.length > 1 && document.querySelector(target)) {
        e.preventDefault();
        lenis.scrollTo(target, { offset: 0 });
      }
    });
  });
  return lenis;
}

// IntersectionObserver-driven arrivals: these fire against the *visual*
// viewport, so they work identically with native scroll, Lenis, and inside
// host iframes whose parent does the scrolling.
function reveals(): void {
  const targets: { el: HTMLElement; delay: number }[] = [];
  const collect = (selector: string, stagger = 0): void => {
    document.querySelectorAll<HTMLElement>(selector).forEach((el, i) => {
      targets.push({ el, delay: (i % 4) * stagger });
    });
  };
  collect(".shift-line");
  collect(".shift-kicker");
  collect(".catalog-head");
  collect(".tile", 0.07);
  collect(".privacy-inner");
  collect(".hardware-inner");
  collect(".close-copy > *", 0.09);
  collect(".act-copy .eyebrow");
  collect(".act-copy .headline");

  const byEl = new Map(targets.map((t) => [t.el, t.delay]));
  gsap.set(targets.map((t) => t.el), ARRIVE);
  const io = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const el = entry.target as HTMLElement;
        gsap.to(el, { ...ARRIVED, delay: byEl.get(el) ?? 0 });
        io.unobserve(el);
      }
    },
    { rootMargin: "0px 0px -10% 0px", threshold: 0.05 }
  );
  targets.forEach((t) => io.observe(t.el));
}

export async function boot(mode: ActMode): Promise<void> {
  document.documentElement.classList.add("motion");
  gsap.registerPlugin(ScrollTrigger);
  if (mode === "scrub") smoothScroll();
  reveals();

  // Build the acts in document order so pin spacing stacks correctly.
  // Per-act resilience (audit 2026-07-14): one missing/failed manifest must
  // degrade only its own act to its static hold pose, not reject Promise.all
  // and silently kill motion for the whole page.
  const sections = Array.from(document.querySelectorAll<HTMLElement>(".act[data-scene]"));
  const settled = await Promise.allSettled(sections.map((s) => loadManifest(s.dataset.scene!)));
  sections.forEach((section, i) => {
    const r = settled[i];
    if (r.status === "fulfilled") {
      buildAct(section, r.value, mode);
    } else {
      console.warn(`[motion] act "${section.dataset.scene}" manifest failed; static hold`, r.reason);
    }
  });
  if (mode === "scrub") ScrollTrigger.refresh();
}
