---
name: orchestrating-gsap-lenis
description: >-
  Sync GSAP animations and ScrollTrigger timelines with Lenis smooth scroll.
  Use when building scroll-driven websites that combine Lenis smooth scrolling
  with GSAP — especially ScrollTrigger, scrubbed timelines, pinning, or scroll
  progress. Fixes the classic problems: two competing requestAnimationFrame
  loops, ScrollTrigger firing at wrong scroll positions, jerky scrub, broken
  anchor links, and stutter under load. Triggers on: "lenis", "smooth scroll",
  "gsap scrolltrigger", "scroll-driven animation", "scrub timeline", "pin
  section on scroll", "sync gsap and lenis".
---

# Orchestrating GSAP + Lenis

## The core problem

GSAP and Lenis both want to own the animation loop (RAF =
`requestAnimationFrame`). If each runs its own RAF loop, they fight:
ScrollTrigger reads a scroll position that Lenis hasn't finished updating,
scrubbed timelines jerk, pinned sections drift, and everything stutters under
load.

**The fix: one RAF loop. Lenis hands control of the loop to GSAP's ticker, and
ScrollTrigger is told to re-read scroll on every Lenis scroll event.**

## Canonical setup

Do these steps in this order. Order matters.

```js
import Lenis from 'lenis'
import { gsap } from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'

// 1. Register plugins FIRST — before any gsap/ScrollTrigger call.
gsap.registerPlugin(ScrollTrigger)

// 2. Create Lenis with autoRaf DISABLED — GSAP will drive the loop.
const lenis = new Lenis({ autoRaf: false })

// 3. Whenever Lenis scrolls, tell ScrollTrigger to recompute.
lenis.on('scroll', ScrollTrigger.update)

// 4. Drive Lenis from GSAP's single ticker (one RAF loop for everything).
//    GSAP's ticker time is in SECONDS; lenis.raf() wants MILLISECONDS.
gsap.ticker.add((time) => {
  lenis.raf(time * 1000)
})

// 5. Kill GSAP lag smoothing so scroll timing stays 1:1 with the ticker.
gsap.ticker.lagSmoothing(0)
```

> If you are on an older Lenis without `autoRaf`, don't start your own
> `requestAnimationFrame(raf)` loop. The `gsap.ticker.add` above IS the loop.
> Running both is the #1 cause of stutter.

## ScrollTrigger timelines

Once the loop is unified, ScrollTrigger works normally — because it now reads
the correct, Lenis-updated scroll position on every tick.

### Scrubbed timeline (progress tied to scroll)

```js
const tl = gsap.timeline({
  scrollTrigger: {
    trigger: '.section',
    start: 'top top',
    end: '+=1500',        // 1500px of scroll distance
    scrub: 1,             // 1s catch-up smoothing; `true` = instant
    pin: true,            // pin the trigger while the timeline plays
    // markers: true,     // uncomment while developing
  },
})

tl.from('.headline', { yPercent: 40, opacity: 0 })
  .from('.subhead', { yPercent: 40, opacity: 0 }, '<0.1')
  .to('.bg', { scale: 1.2 }, 0)
```

Because ScrollTrigger is scrubbing off the shared ticker, the timeline
position stays locked to the smoothed scroll — no double-easing, no jerk.

### Reveal on enter (play once, not scrubbed)

```js
gsap.utils.toArray('.reveal').forEach((el) => {
  gsap.from(el, {
    y: 60,
    opacity: 0,
    duration: 0.8,
    ease: 'power2.out',
    scrollTrigger: { trigger: el, start: 'top 80%' },
  })
})
```

### Horizontal scroll section

```js
const track = document.querySelector('.h-track')
gsap.to(track, {
  x: () => -(track.scrollWidth - window.innerWidth),
  ease: 'none',
  scrollTrigger: {
    trigger: '.h-wrap',
    start: 'top top',
    end: () => '+=' + (track.scrollWidth - window.innerWidth),
    scrub: true,
    pin: true,
    invalidateOnRefresh: true, // recompute the () => values on resize
  },
})
```

## Anchor links / programmatic scroll

Native `scrollIntoView` and `#hash` jumps bypass Lenis. Route them through
Lenis so smooth scroll (and ScrollTrigger) stay in sync:

```js
document.querySelectorAll('a[href^="#"]').forEach((a) => {
  a.addEventListener('click', (e) => {
    e.preventDefault()
    lenis.scrollTo(a.getAttribute('href'))
  })
})
```

`lenis.scrollTo(target, { offset, duration, immediate })` accepts a selector,
element, or number.

## Refresh timing

If ScrollTrigger measures the page before fonts/images/layout settle, `start`
and `end` land in the wrong place. Refresh after load and after any layout
change:

```js
window.addEventListener('load', () => ScrollTrigger.refresh())
```

Use function-based `start`/`end` values (`() => ...`) plus
`invalidateOnRefresh: true` so measurements recompute on resize instead of
caching stale pixel values.

## Cleanup (SPA / React / route changes)

Every `gsap.ticker.add`, ScrollTrigger, and Lenis instance leaks if not torn
down. In a component:

```js
// React example
useEffect(() => {
  gsap.registerPlugin(ScrollTrigger)
  const lenis = new Lenis({ autoRaf: false })
  lenis.on('scroll', ScrollTrigger.update)
  const update = (time) => lenis.raf(time * 1000)
  gsap.ticker.add(update)
  gsap.ticker.lagSmoothing(0)

  const ctx = gsap.context(() => {
    /* your timelines / triggers here */
  })

  return () => {
    ctx.revert()               // kill this scope's tweens + triggers
    gsap.ticker.remove(update) // stop driving Lenis
    lenis.destroy()            // remove listeners + restore native scroll
  }
}, [])
```

## Checklist / common failures

- **Stutter or double-smoothing** → you have two RAF loops. Ensure
  `autoRaf: false` and no manual `requestAnimationFrame(raf)`; only
  `gsap.ticker.add` drives Lenis.
- **ScrollTrigger fires at wrong position** → missing
  `lenis.on('scroll', ScrollTrigger.update)`.
- **Scrub feels laggy/delayed** → you forgot `gsap.ticker.lagSmoothing(0)`.
- **Triggers off after load** → call `ScrollTrigger.refresh()` on `load`.
- **Anchor links jump instantly** → route them through `lenis.scrollTo`.
- **Pin jumps on resize** → use function-based end values +
  `invalidateOnRefresh: true`.
- **Memory leak / triggers pile up on navigation** → remove the ticker
  callback, `lenis.destroy()`, and `ScrollTrigger.getAll().forEach(t => t.kill())`
  (or `gsap.context().revert()`).

## Reference

- Lenis README (GSAP section): https://github.com/darkroomengineering/lenis
- GSAP ScrollTrigger docs: https://gsap.com/docs/v3/Plugins/ScrollTrigger/
