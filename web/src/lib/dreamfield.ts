// The hero's living sky: a port of the product's DreamCanvas ambient weather
// (value-noise lattice + Line Field 2.0, the same math the glasses idle with).
// Two palette bands — the memory teal sky and a warm energy accent — drift on
// a value-noise clock; the whole field leans gently toward the pointer.

const TAU = Math.PI * 2;

// Exported for unit coverage: this smooth value-noise is the field's math core;
// initDreamField below is DOM/canvas-bound, but the noise is pure and testable.
export function vnoise(x: number): number {
  const h = (n: number) => {
    n = ((Math.floor(n) % 289) + 289) % 289;
    return (((n * 34 + 1) * n) % 289) / 144.5 - 1.0;
  };
  const x0 = Math.floor(x);
  const f = x - x0;
  const u = f * f * (3 - 2 * f);
  return h(x0) + (h(x0 + 1) - h(x0)) * u;
}

export function initDreamField(canvas: HTMLCanvasElement, host: Element): void {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  let W = 0;
  let H = 0;
  const N = 26;
  let px = 0.5;
  let py = 0.42;
  let tx = 0.5;
  let ty = 0.42;

  function resize(): void {
    const dpr = Math.min(devicePixelRatio || 1, 2);
    W = canvas.clientWidth;
    H = canvas.clientHeight;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function draw(t: number): void {
    const c = ctx!;
    c.clearRect(0, 0, W, H);
    const cx = W * (0.5 + (px - 0.5) * 0.05);
    const cy = H * (0.42 + (py - 0.42) * 0.07);
    const R = Math.min(W, H) * 0.46;
    const pressure = 0.5 + 0.5 * vnoise(t * 0.11);
    const energy = Math.max(0, vnoise(t * 0.31 + 40));
    const amp = 0.3 + 0.4 * pressure + 0.3 * energy;
    // sky: the HUD memory teal (#2CC79A) breathing toward mint
    const sky = `rgb(${Math.round(44 - pressure * 20)},${Math.round(199 - pressure * 60)},${Math.round(154 + pressure * 80)})`;
    const eng = `rgb(${Math.round(120 + energy * 120)},${Math.round(120 - energy * 30)},82)`;
    const phase = t * 0.05;
    c.lineWidth = 1.1;
    c.lineCap = "round";
    for (let i = 0; i < N; i++) {
      const a = phase + (i * TAU) / N;
      const wob = 0.72 + 0.55 * vnoise(i * 5.1 + t * 0.07);
      const ax = cx + R * wob * Math.cos(a);
      const ay = cy + R * wob * Math.sin(a);
      const n = vnoise(i * 3.7 + phase * 2.1);
      const dn = vnoise(i * 3.7 + phase * 2.1 + 0.5) - n;
      const ca = a + Math.PI / 2 + dn * 1.8;
      const ln = (14 + (n * 0.5 + 0.5) * 20) * (Math.min(W, H) / 300);
      c.strokeStyle = i % 3 === 0 ? eng : sky;
      c.globalAlpha = (0.35 + amp * 0.4) * 0.5;
      c.beginPath();
      c.moveTo(ax - ln * Math.cos(ca), ay - ln * Math.sin(ca));
      c.lineTo(ax + ln * Math.cos(ca), ay + ln * Math.sin(ca));
      c.stroke();
    }
    for (let j = 0; j < 3; j++) {
      c.globalAlpha = 0.05 + j * 0.02;
      c.strokeStyle = sky;
      c.lineWidth = Math.min(W, H) * 0.02;
      c.beginPath();
      c.arc(cx, cy, R * (0.52 - j * 0.11), 0, TAU);
      c.stroke();
    }
    c.globalAlpha = 1;
  }

  addEventListener("resize", resize, { passive: true });
  addEventListener(
    "pointermove",
    (e) => {
      tx = e.clientX / innerWidth;
      ty = e.clientY / innerHeight;
    },
    { passive: true }
  );
  resize();

  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    draw(7.0); // one still frame of weather
    return;
  }

  const t0 = performance.now();
  let visible = true;
  let raf: number | null = null;
  const frame = (now: number): void => {
    raf = null;
    px += (tx - px) * 0.04;
    py += (ty - py) * 0.04;
    draw((now - t0) / 1000);
    if (visible && !document.hidden) raf = requestAnimationFrame(frame);
  };
  const kick = (): void => {
    if (!raf && visible && !document.hidden) raf = requestAnimationFrame(frame);
  };
  new IntersectionObserver((entries) => {
    visible = entries[0].isIntersecting;
    kick();
  }).observe(host);
  document.addEventListener("visibilitychange", kick);
  kick();
}
