/* figment.js — the no-code lens builder's brain (INNOVATION_SESSION 5, Category 1).
 *
 * A figment is data, not code: scenes, timed/event transitions, pulses. This is
 * the pure logic behind landing/lens-builder.html — the budget rules (in exact
 * lockstep with reality_compiler/v2/figment.py; a Python test asserts the
 * numbers match), the recipe templates, the proof/safety card, and the
 * canonical export. No DOM here, so it runs in the browser AND under Node for
 * tests.
 *
 * The point of the whole platform: the installer re-checks this proof; it never
 * trusts the author. Same as the phone and the Brain.
 */
(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) module.exports = factory();
  else root.LensKit = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // -- budgets (keep in lockstep with reality_compiler/v2/figment.py) --------
  var B = {
    MAX_SCENES: 32, MAX_COUNTERS: 8, MAX_LINES: 5, MAX_TEXT_LEN: 24,
    MAX_PULSE_HZ: 4.0, MIN_SCENE_SEC: 0.5, MAX_SCENE_SEC: 24 * 3600.0,
    MAX_NAME_LEN: 40, MAX_BRANCHES: 4,
    MAX_GLYPHS: 6, MAX_GLYPH_POINTS: 24,
    MAX_COUNTER_OPS: 4, MAX_EMIT_TAG_LEN: 16, COUNTER_HI: 9999,
    MAX_SLOTS: 8,
  };
  // {slot:<name>} — a named host slot (default {slot} is name "").
  var SLOT_TOKEN_RE = /\{slot:(\w+)\}/g;
  function _namedSlots(fig) {
    var seen = {};
    (fig.scenes ? Object.keys(fig.scenes) : []).forEach(function (sid) {
      ((fig.scenes[sid].lines) || []).forEach(function (ln) {
        var m, re = /\{slot:(\w+)\}/g;
        while ((m = re.exec(String(ln.content || "")))) seen[m[1]] = 1;
      });
    });
    return Object.keys(seen).sort();
  }
  var END = "@end", SELF = "@self";
  var COLORS = ["background", "surface", "text_primary", "text_secondary",
    "accent_memory", "accent_attention", "accent_success", "accent_error",
    "border_subtle", "status_paused"];
  var SIZES = ["sm", "md", "lg"];
  // token -> hex, for the live ring preview (mirrors halo-lua/display/palette.lua)
  var HEX = {
    background: "#000000", surface: "#0E1416", text_primary: "#ECF0F1",
    text_secondary: "#A8B8C0", accent_memory: "#2CC79A", accent_attention: "#E06B52",
    accent_success: "#56D364", accent_error: "#E05252", border_subtle: "#2A3C44",
    status_paused: "#8FA8B2",
  };

  // -- model -----------------------------------------------------------------
  function line(content, opts) {
    opts = opts || {};
    return { content: String(content).slice(0, B.MAX_TEXT_LEN),
             row: opts.row || 0, size: opts.size || "md",
             color: opts.color || "text_primary" };
  }
  function scene(id, o) {
    o = o || {};
    var s = { id: id, lines: o.lines || [] };
    if (o.duration_sec != null) s.duration_sec = o.duration_sec;
    if (o.on_timeout) s.on_timeout = o.on_timeout;      // [{target, emit?}]
    if (o.on) s.on = o.on;                              // {event: {target}}
    if (o.pulse) s.pulse = o.pulse;                     // {window_sec, rate_hz, color}
    if (o.tick) s.tick = o.tick;
    if (o.glyphs) s.glyphs = o.glyphs;                  // [{points:[[x,y]..], color, width}]
    if (o.cadence) s.cadence = o.cadence;               // {in_s, hold_s, out_s} breathing
    return s;
  }
  function counter(name, o) {                            // a bounded, saturating tally
    o = o || {};
    return { name: name, start: o.start || 0, lo: o.lo || 0, hi: o.hi == null ? B.COUNTER_HI : o.hi };
  }
  function inc(name, by) { return { counter: name, op: "inc", amount: by == null ? 1 : by }; }
  function zero(name) { return { counter: name, op: "set", amount: 0 }; }
  // one painted stroke: a polyline in normalized 0..1 display coords. Coords are
  // rounded to 4 places to match figment.py's canonical form (signature-stable).
  function r4(n) { return Math.round(Math.max(0, Math.min(1, +n)) * 1e4) / 1e4; }
  function glyph(points, opts) {
    opts = opts || {};
    return { points: (points || []).map(function (p) { return [r4(p[0]), r4(p[1])]; })
               .slice(0, B.MAX_GLYPH_POINTS),
             color: opts.color || "accent_attention", width: opts.width || "md" };
  }
  function figment(name, initial) {
    return { id: "", name: name || "My lens", initial: initial || "",
             version: 2, scenes: {}, counters: {}, meta: {} };
  }
  function addScene(fig, s) { fig.scenes[s.id] = s; if (!fig.initial) fig.initial = s.id; return s; }

  // -- recipe templates (the no-coder's on-ramp) -----------------------------
  function tInterval(o) {
    o = o || {}; var work = o.work || 180, rest = o.rest || 30;
    var f = figment(o.name || "Interval timer", "work");
    addScene(f, scene("work", {
      duration_sec: work, tick: "countdown",
      lines: [line("WORK", { row: 0, size: "lg", color: "accent_memory" })],
      pulse: { window_sec: Math.min(10, work), rate_hz: 2.0, color: "accent_attention" },
      on_timeout: [{ target: "rest" }],
      on: { double: { target: END } },
    }));
    addScene(f, scene("rest", {
      duration_sec: rest, tick: "countdown",
      lines: [line("REST", { row: 0, size: "lg", color: "accent_success" })],
      on_timeout: [{ target: "work" }],
      on: { double: { target: END } },
    }));
    return f;
  }
  function tCountdown(o) {
    o = o || {}; var secs = o.seconds || 300;
    var f = figment(o.name || "Countdown", "run");
    addScene(f, scene("run", {
      duration_sec: secs, tick: "countdown",
      lines: [line(o.label || "TIME", { row: 0, size: "lg", color: "accent_memory" })],
      pulse: { window_sec: Math.min(10, secs), rate_hz: 2.0, color: "accent_attention" },
      on_timeout: [{ target: END }],
      on: { double: { target: END } },
    }));
    return f;
  }
  function tChecklist(o) {
    o = o || {}; var steps = o.steps || ["Step one", "Step two", "Step three"];
    var f = figment(o.name || "Checklist ritual", "s0");
    for (var i = 0; i < steps.length; i++) {
      var next = i + 1 < steps.length ? "s" + (i + 1) : END;
      addScene(f, scene("s" + i, {
        lines: [line(String(steps[i]).slice(0, B.MAX_TEXT_LEN), { row: 0, size: "md" }),
                line("nod / double-tap →", { row: 2, size: "sm", color: "text_secondary" })],
        on: { double: { target: next }, "imu:nod": { target: next } },
      }));
    }
    return f;
  }
  function tBreathing(o) {
    o = o || {}; var inS = o.in_s || 4, hold = o.hold_s || 4, out = o.out_s || 4;
    var f = figment(o.name || "Box breathing", "in");
    var mk = function (id, label, dur, nxt, col) {
      return scene(id, {
        duration_sec: dur, lines: [line(label, { row: 0, size: "lg", color: col })],
        pulse: { window_sec: dur, rate_hz: 1.0, color: col },
        on_timeout: [{ target: nxt }], on: { double: { target: END } },
      });
    };
    addScene(f, mk("in", "BREATHE IN", inS, "hold1", "accent_memory"));
    addScene(f, mk("hold1", "HOLD", hold, "out", "text_secondary"));
    addScene(f, mk("out", "BREATHE OUT", out, "hold2", "accent_success"));
    addScene(f, mk("hold2", "HOLD", hold, "in", "text_secondary"));
    return f;
  }
  // A rep counter: nod to add one, hold to reset, double-tap to finish. Shows
  // off counters + on-glass gestures + a painted tally arc + the {count} token.
  function tReps(o) {
    o = o || {};
    var f = figment(o.name || "Rep counter", "count");
    f.counters.reps = counter("reps", { hi: 999 });
    addScene(f, scene("count", {
      lines: [line("{count:reps}", { row: 1, size: "lg", color: "accent_memory" }),
              line(o.label || "reps", { row: 0, size: "sm", color: "text_secondary" }),
              line("nod +1 · hold 0 · ✕✕ done", { row: 4, size: "sm", color: "text_secondary" })],
      glyphs: [glyph([[0.26, 0.64], [0.5, 0.71], [0.74, 0.64]], { color: "accent_memory", width: "md" })],
      on: { "imu:nod": { target: SELF, counter_ops: [inc("reps")] },
            "long": { target: SELF, counter_ops: [zero("reps")] },
            "double": { target: END } },
    }));
    return f;
  }
  // A deep-work session: a painted sigil that BREATHES while you focus, then a
  // gentle end-pulse and a checkmark. Paint + cadence + pulse + countdown.
  function tFocus(o) {
    o = o || {}; var secs = (o.minutes || 25) * 60;
    var f = figment(o.name || "Deep focus", "work");
    addScene(f, scene("work", {
      duration_sec: secs, tick: "countdown",
      lines: [line("FOCUS", { row: 0, size: "lg", color: "accent_memory" })],
      glyphs: [glyph([[0.5, 0.34], [0.66, 0.5], [0.5, 0.66], [0.34, 0.5], [0.5, 0.34]],
                     { color: "accent_memory", width: "md" })],
      cadence: { in_s: 4, hold_s: 2, out_s: 4 },
      pulse: { window_sec: Math.min(15, secs), rate_hz: 1.5, color: "accent_attention" },
      on_timeout: [{ target: "done" }], on: { double: { target: END } },
    }));
    addScene(f, scene("done", {
      duration_sec: 4,
      lines: [line("DONE", { row: 0, size: "lg", color: "accent_success" })],
      glyphs: [glyph([[0.34, 0.54], [0.45, 0.64], [0.68, 0.4]], { color: "accent_success", width: "lg" })],
      on_timeout: [{ target: END }], on: { double: { target: END } },
    }));
    return f;
  }
  // A live scoreboard: tap for us, double-tap for them, hold to reset. Two
  // saturating counters + gestures, the score painted on the glass.
  function tScore(o) {
    o = o || {};
    var f = figment(o.name || "Scoreboard", "play");
    f.counters.us = counter("us", { hi: 99 });
    f.counters.them = counter("them", { hi: 99 });
    addScene(f, scene("play", {
      lines: [line("{count:us} : {count:them}", { row: 1, size: "lg", color: "text_primary" }),
              line("us   ·   them", { row: 0, size: "sm", color: "text_secondary" }),
              line("tap us · ✕✕ them · hold 0", { row: 4, size: "sm", color: "text_secondary" })],
      glyphs: [glyph([[0.5, 0.26], [0.5, 0.58]], { color: "border_subtle", width: "sm" })],
      on: { single: { target: SELF, counter_ops: [inc("us")] },
            double: { target: SELF, counter_ops: [inc("them")] },
            long: { target: SELF, counter_ops: [zero("us"), zero("them")] } },
    }));
    return f;
  }
  var TEMPLATES = [
    { id: "reps", name: "Rep counter", blurb: "Nod to count — a live tally you paint on the glass.", make: tReps },
    { id: "focus", name: "Deep focus", blurb: "A sigil that breathes while you work, then lands.", make: tFocus },
    { id: "score", name: "Scoreboard", blurb: "Tap us, double-tap them. The score, on your eye.", make: tScore },
    { id: "breathing", name: "Box breathing", blurb: "In · hold · out · hold, gently breathing the ring.", make: tBreathing },
    { id: "interval", name: "Interval timer", blurb: "Work / rest rounds — pulses near the switch.", make: tInterval },
    { id: "checklist", name: "Checklist ritual", blurb: "Named stages you advance with a nod.", make: tChecklist },
    { id: "countdown", name: "Countdown", blurb: "A single timer that pulses as it lands.", make: tCountdown },
  ];

  // -- showcase lenses for the tutorial: each pushes a different edge ---------
  // These exist to make people say "wait, it can do THAT?" — they use the whole
  // grammar (gestures, counters, guards, paint, cadence, world-triggers, the
  // performance ledger) and every one still passes the exact same budget proof.
  function _petal(cx, cy, ang, len, wid) {
    var ox = Math.cos(ang), oy = Math.sin(ang), px = -oy, py = ox;
    return [[cx, cy],
            [cx + ox * len * 0.5 + px * wid, cy + oy * len * 0.5 + py * wid],
            [cx + ox * len, cy + oy * len],
            [cx + ox * len * 0.5 - px * wid, cy + oy * len * 0.5 - py * wid],
            [cx, cy]];
  }
  function _mandala() {
    var g = [], N = 6;
    for (var k = 0; k < N; k++)
      g.push(glyph(_petal(0.5, 0.5, (k / N) * Math.PI * 2, 0.34, 0.12),
                   { color: k % 2 ? "accent_memory" : "accent_attention", width: "sm" }));
    return g;
  }
  // Steer with your head: a deck you flip with nod / shake / peek — no hands.
  function shHeadControl() {
    var f = figment("Head-steered deck", "a");
    var deck = [["FOCUS", "accent_memory"], ["BREATHE", "accent_success"], ["STAND TALL", "accent_attention"]];
    deck.forEach(function (d, i) {
      var next = "abc"[(i + 1) % deck.length], prev = "abc"[(i + deck.length - 1) % deck.length];
      addScene(f, scene("abc"[i], {
        lines: [line(d[0], { row: 1, size: "lg", color: d[1] }),
                line("nod → · shake ← · look up = done", { row: 4, size: "sm", color: "text_secondary" })],
        glyphs: [glyph([[0.30, 0.30], [0.70, 0.30]], { color: d[1], width: "sm" })],
        on: { "imu:nod": { target: next }, "imu:shake": { target: prev }, "imu:peek": { target: END } },
      }));
    });
    return f;
  }
  // Paint that breathes: a hand-painted mandala on a slow breathing envelope.
  function shMandala() {
    var f = figment("Breathing mandala", "breathe");
    addScene(f, scene("breathe", {
      duration_sec: 300, tick: "countdown",
      lines: [line("BREATHE", { row: 0, size: "sm", color: "accent_memory" }),
              line("in 4 · hold 4 · out 6", { row: 3, size: "sm", color: "text_secondary" })],
      glyphs: _mandala(),
      cadence: { in_s: 4, hold_s: 4, out_s: 6 },
      pulse: { window_sec: 12, rate_hz: 0.8, color: "accent_memory" },
      on_timeout: [{ target: END }], on: { double: { target: END } },
    }));
    return f;
  }
  // The world reaches in: one lens, three real-world triggers — a place you
  // arrive at, a bonded partner coming near, a $6 BLE button out in the world.
  function shWorld() {
    var f = figment("When the world moves", "wait");
    addScene(f, scene("wait", {
      lines: [line("READY", { row: 1, size: "lg", color: "text_secondary" }),
              line("arrive · partner near · button", { row: 4, size: "sm", color: "text_secondary" })],
      glyphs: [glyph([[0.5, 0.28], [0.5, 0.5], [0.68, 0.5]], { color: "border_subtle", width: "sm" })],
      on: { "place:enter": { target: "here" }, "bond:near": { target: "them" }, "ble:3": { target: "btn" } },
    }));
    var beat = function (id, txt, col, back) {
      addScene(f, scene(id, {
        duration_sec: 4, tick: "countdown",
        lines: [line(txt, { row: 1, size: "lg", color: col })],
        pulse: { window_sec: 3, rate_hz: 1.5, color: col },
        on_timeout: [{ target: back }], on: { double: { target: END } },
      }));
    };
    beat("here", "YOU'RE HERE", "accent_success", "wait");
    beat("them", "THEY'RE NEAR", "accent_memory", "wait");
    beat("btn", "PRESSED", "accent_attention", "wait");
    return f;
  }
  // Data you keep: every nod is logged to your Vault performance ledger, so the
  // lens becomes an instrument — a rep history, a meds-taken record.
  function shKeep() {
    var f = figment("Logged reps", "count");
    f.counters.reps = counter("reps", { hi: 999 });
    addScene(f, scene("count", {
      lines: [line("{count:reps}", { row: 1, size: "lg", color: "accent_memory" }),
              line("each nod is saved", { row: 4, size: "sm", color: "text_secondary" })],
      glyphs: [glyph([[0.28, 0.66], [0.5, 0.72], [0.72, 0.66]], { color: "accent_memory", width: "md" })],
      on: { "imu:nod": { target: SELF, counter_ops: [inc("reps")], emit: "rep", record: true },
            "long": { target: SELF, counter_ops: [zero("reps")] },
            "double": { target: END } },
    }));
    return f;
  }
  // Push every limit: paint + a counter + a guard that decides + a gesture + a
  // world-trigger + the ledger, fused into one signed, provable ritual.
  function shFusion() {
    var f = figment("The whole stack", "arrive");
    f.counters.rounds = counter("rounds", { hi: 9 });
    addScene(f, scene("arrive", {
      lines: [line("AT THE GYM?", { row: 1, size: "md", color: "text_secondary" }),
              line("arrive to begin · ✕✕ now", { row: 4, size: "sm", color: "text_secondary" })],
      glyphs: _mandala().slice(0, 3),
      on: { "place:enter": { target: "work" }, "double": { target: "work" } },
    }));
    addScene(f, scene("work", {
      duration_sec: 30, tick: "countdown",
      lines: [line("ROUND {count:rounds}", { row: 0, size: "lg", color: "accent_attention" })],
      glyphs: [glyph([[0.3, 0.7], [0.5, 0.62], [0.7, 0.7]], { color: "accent_attention", width: "md" })],
      pulse: { window_sec: 5, rate_hz: 2.0, color: "accent_attention" },
      on_timeout: [{ target: "rest", counter_ops: [inc("rounds")], emit: "round", record: true }],
      on: { double: { target: END } },
    }));
    addScene(f, scene("rest", {
      duration_sec: 15, tick: "countdown",
      lines: [line("BREATHE", { row: 1, size: "lg", color: "accent_success" })],
      cadence: { in_s: 4, hold_s: 2, out_s: 4 },
      // a guard decides: after 3 rounds, you're done — else back to work
      on_timeout: [{ target: "done", when: { counter: "rounds", cmp: "ge", value: 3 } },
                   { target: "work" }],
      on: { double: { target: END } },
    }));
    addScene(f, scene("done", {
      duration_sec: 5,
      lines: [line("DONE ×{count:rounds}", { row: 1, size: "lg", color: "accent_success" })],
      glyphs: [glyph([[0.34, 0.54], [0.45, 0.64], [0.68, 0.4]], { color: "accent_success", width: "lg" })],
      on_timeout: [{ target: END }], on: { double: { target: END } },
    }));
    return f;
  }
  // -- the loop between the glass and the whole stack -------------------------
  // These are the "no way" lenses: the world feeds them (place/bond/ble events),
  // the Brain streams into {slot} (translations, an LLM answer, a camera label,
  // a resurfaced memory), and they emit back (a heartbeat, a logged rep). Every
  // one is a real, budget-proven figment — the tour simulates the live feed.
  function _ring(cx, cy, r) {
    var pts = [], N = 13;
    for (var i = 0; i <= N; i++) { var a = (i / N) * Math.PI * 2; pts.push([cx + Math.cos(a) * r, cy + Math.sin(a) * r]); }
    return pts;
  }
  function _heart(cx, cy, s) {
    var pts = [], N = 20;
    for (var i = 0; i <= N; i++) {
      var t = (i / N) * Math.PI * 2, x = 16 * Math.pow(Math.sin(t), 3);
      var y = 13 * Math.cos(t) - 5 * Math.cos(2 * t) - 2 * Math.cos(3 * t) - Math.cos(4 * t);
      pts.push([cx + x * s, cy - y * s]);
    }
    return pts;
  }
  function _heartGlyph(col) { return [glyph(_heart(0.5, 0.44, 0.0155), { color: col, width: "sm" })]; }
  // -- a small kit of tasteful signature glyphs (normalized 0..1 coords) ------
  function _reticle(cx, cy, r, col) {                    // an eye/scan ring + ticks
    return [glyph(_ring(cx, cy, r), { color: col, width: "sm" }),
            glyph([[cx - r * 1.7, cy], [cx - r * 0.9, cy]], { color: col, width: "sm" }),
            glyph([[cx + r * 0.9, cy], [cx + r * 1.7, cy]], { color: col, width: "sm" })];
  }
  function _wave(cx, cy, w, h, col) {                    // a voice waveform
    var bars = [0.35, 0.7, 0.5, 1, 0.62, 0.85, 0.45], n = bars.length, pts = [], x0 = cx - w / 2;
    for (var i = 0; i < n; i++) { var x = x0 + (i / (n - 1)) * w, a = bars[i] * h;
      pts.push([x, cy - a]); pts.push([x, cy + a]); }
    return glyph(pts, { color: col, width: "sm" });
  }
  function _flame(cx, cy, s, col) {                      // a small ember flame
    var p = [[0, 0.9], [-0.5, 0.3], [-0.28, -0.2], [0, -0.9], [0.28, -0.2], [0.5, 0.3], [0, 0.9]];
    return glyph(p.map(function (q) { return [cx + q[0] * s, cy - q[1] * s]; }), { color: col, width: "sm" });
  }
  function _path(cx, cy, col) {                          // a doorway + a path ahead
    return [glyph([[cx - 0.09, cy + 0.12], [cx - 0.06, cy - 0.1], [cx + 0.06, cy - 0.1], [cx + 0.09, cy + 0.12]], { color: col, width: "sm" }),
            glyph([[cx - 0.02, cy + 0.13], [cx, cy + 0.02], [cx + 0.02, cy + 0.13]], { color: "border_subtle", width: "sm" })];
  }
  function _check(cx, cy, s, col) {                      // a checkmark
    return glyph([[cx - s, cy], [cx - s * 0.2, cy + s * 0.8], [cx + s * 1.2, cy - s * 0.9]], { color: col, width: "md" });
  }
  function _bar(cx, cy, w, col) {                        // a barbell / form bar
    return [glyph([[cx - w, cy], [cx + w, cy]], { color: col, width: "lg" }),
            glyph([[cx - w, cy - 0.05], [cx - w, cy + 0.05]], { color: col, width: "md" }),
            glyph([[cx + w, cy - 0.05], [cx + w, cy + 0.05]], { color: col, width: "md" })];
  }

  // Whisper — read/hear any language, live. Camera OCR + mic → Brain/cloud
  // translate → the words stream onto {slot}.
  function shWhisper() {
    var f = figment("Whisper — live translate", "hear");
    addScene(f, scene("hear", {
      duration_sec: 1.6, tick: "countup",
      lines: [line("ES → EN", { row: 0, size: "sm", color: "accent_memory" }),
              line("listening…", { row: 1, size: "md", color: "text_secondary" })],
      glyphs: [_wave(0.5, 0.66, 0.34, 0.07, "accent_memory")],
      on_timeout: [{ target: "live" }], on: { "text": { target: "live" }, "double": { target: END } },
    }));
    addScene(f, scene("live", {
      lines: [line("{slot}", { row: 1, size: "md", color: "text_primary" }),
              line("ES → EN", { row: 0, size: "sm", color: "accent_memory" }),
              line("▸ live", { row: 3, size: "sm", color: "accent_memory" })],
      glyphs: [glyph([[0.16, 0.8], [0.36, 0.8]], { color: "accent_memory", width: "sm" }),
               glyph([[0.64, 0.8], [0.84, 0.8]], { color: "accent_memory", width: "sm" })],
      cadence: { in_s: 2, hold_s: 1, out_s: 2 },
      on: { "text": { target: SELF }, "double": { target: END } },
    }));
    return f;
  }
  // Ask — your Brain, on glass. Double-tap & speak → emit "ask" → the Brain
  // answers from your own memory (or cloud) → the answer lands in {slot}.
  function shAsk() {
    var f = figment("Ask — your Brain, on glass", "idle");
    addScene(f, scene("idle", {
      lines: [line("JUNO", { row: 0, size: "sm", color: "accent_memory" }),
              line("Ask me anything", { row: 1, size: "md", color: "text_secondary" }),
              line("double-tap, then speak", { row: 3, size: "sm", color: "text_secondary" })],
      glyphs: [glyph(_ring(0.5, 0.64, 0.05), { color: "border_subtle", width: "sm" })],
      cadence: { in_s: 2, hold_s: 1, out_s: 2 },
      on: { "double": { target: "hear", emit: "ask" } },
    }));
    addScene(f, scene("hear", {
      duration_sec: 2, tick: "countup",
      lines: [line("JUNO", { row: 0, size: "sm", color: "accent_memory" }),
              line("listening…", { row: 1, size: "md", color: "accent_attention" })],
      glyphs: [_wave(0.5, 0.66, 0.34, 0.07, "accent_attention")],
      pulse: { window_sec: 2, rate_hz: 1.5, color: "accent_attention" },
      on_timeout: [{ target: "answer" }], on: { "text": { target: "answer" }, "double": { target: "idle" } },
    }));
    addScene(f, scene("answer", {
      lines: [line("ANSWER", { row: 0, size: "sm", color: "accent_memory" }),
              line("{slot}", { row: 1, size: "md", color: "text_primary" }),
              line("⛨ from your memory", { row: 3, size: "sm", color: "accent_memory" })],
      glyphs: [_check(0.5, 0.72, 0.05, "accent_success")],
      on: { "text": { target: SELF }, "double": { target: "idle" } },
    }));
    return f;
  }
  // Tethered — feel a bonded partner across the world. Their presence fires
  // bond:near, their mood-weather tints the ring, you emit a heartbeat back.
  function shTethered() {
    var f = figment("Tethered — feel them near", "away");
    addScene(f, scene("away", {
      lines: [line("TETHERED", { row: 0, size: "sm", color: "accent_memory" }),
              line("· · ·", { row: 1, size: "lg", color: "text_secondary" }),
              line("2,400 miles away", { row: 3, size: "sm", color: "text_secondary" })],
      glyphs: _heartGlyph("border_subtle"), cadence: { in_s: 4, hold_s: 1, out_s: 4 },
      on: { "bond:near": { target: "near" }, "text": { target: SELF }, "double": { target: END } },
    }));
    addScene(f, scene("near", {
      duration_sec: 6, tick: "countdown",
      lines: [line("TETHERED", { row: 0, size: "sm", color: "accent_memory" }),
              line("She's near", { row: 1, size: "lg", color: "accent_memory" }),
              line("a heartbeat away", { row: 3, size: "sm", color: "text_secondary" })],
      glyphs: _heartGlyph("accent_memory"), pulse: { window_sec: 6, rate_hz: 1.1, color: "accent_memory" },
      on_timeout: [{ target: "away", emit: "beat", record: true }], on: { "double": { target: END } },
    }));
    return f;
  }
  // Threshold — your world reacts to where you are. Arriving fires place:enter
  // and the right ritual just begins.
  function shThreshold() {
    var f = figment("Threshold — arrive & begin", "home");
    addScene(f, scene("home", {
      lines: [line("THRESHOLD", { row: 0, size: "sm", color: "accent_memory" }),
              line("You're home", { row: 1, size: "md", color: "text_secondary" }),
              line("walk somewhere to begin", { row: 3, size: "sm", color: "text_secondary" })],
      glyphs: _path(0.5, 0.6, "accent_memory"), cadence: { in_s: 3, hold_s: 1, out_s: 3 },
      on: { "place:enter": { target: "gym" }, "double": { target: END } },
    }));
    addScene(f, scene("gym", {
      duration_sec: 5, tick: "countdown",
      lines: [line("ARRIVED · GYM", { row: 0, size: "sm", color: "accent_attention" }),
              line("Round 1", { row: 1, size: "lg", color: "accent_attention" }),
              line("your ritual begins", { row: 3, size: "sm", color: "text_secondary" })],
      glyphs: [_check(0.5, 0.72, 0.05, "accent_attention")],
      pulse: { window_sec: 3, rate_hz: 2.0, color: "accent_attention" },
      on_timeout: [{ target: "home" }], on: { "place:exit": { target: "home" }, "double": { target: END } },
    }));
    return f;
  }
  // Second Sight — the camera whispers what it sees. Glance + hold → emit
  // "look" → vision (local or cloud) names it into {slot}.
  function shSecondSight() {
    var f = figment("Second Sight — name anything", "look");
    addScene(f, scene("look", {
      lines: [line("SECOND SIGHT", { row: 0, size: "sm", color: "accent_memory" }),
              line("Glance + hold", { row: 1, size: "md", color: "text_secondary" }),
              line("to name what you see", { row: 3, size: "sm", color: "text_secondary" })],
      glyphs: _reticle(0.5, 0.44, 0.11, "accent_memory"),
      cadence: { in_s: 2, hold_s: 1, out_s: 2 },
      on: { "long": { target: "seen", emit: "look" }, "double": { target: END } },
    }));
    addScene(f, scene("seen", {
      lines: [line("IDENTIFIED", { row: 0, size: "sm", color: "accent_success" }),
              line("{slot}", { row: 1, size: "md", color: "accent_success" }),
              line("hold to look again ↻", { row: 3, size: "sm", color: "text_secondary" })],
      glyphs: _reticle(0.5, 0.44, 0.11, "accent_success"),
      on: { "text": { target: SELF }, "long": { target: "look" }, "double": { target: END } },
    }));
    return f;
  }
  // Ember — your own memory, handed back at the perfect moment. Standing where
  // it happened (place:enter) the Vault surfaces a line into {slot}.
  function shEmber() {
    var f = figment("Ember — memory, returned", "quiet");
    addScene(f, scene("quiet", {
      lines: [line("EMBER", { row: 0, size: "sm", color: "accent_memory" }),
              line("· here ·", { row: 1, size: "md", color: "text_secondary" }),
              line("a memory sleeps here", { row: 3, size: "sm", color: "text_secondary" })],
      glyphs: [_flame(0.5, 0.62, 0.09, "border_subtle")],
      cadence: { in_s: 5, hold_s: 2, out_s: 5 },
      on: { "place:enter": { target: "back" }, "text": { target: "back" }, "double": { target: END } },
    }));
    addScene(f, scene("back", {
      lines: [line("A YEAR AGO", { row: 0, size: "sm", color: "accent_memory" }),
              line("{slot}", { row: 1, size: "md", color: "text_primary" }),
              line("where it happened", { row: 3, size: "sm", color: "text_secondary" })],
      glyphs: [_flame(0.5, 0.62, 0.09, "accent_attention")],
      cadence: { in_s: 5, hold_s: 2, out_s: 5 },
      on: { "text": { target: SELF }, "double": { target: END } },
    }));
    return f;
  }
  // Coach — the camera judges your FORM, not your reps. The phone's pose + the
  // Brain stream a live cue into {slot}; a clean rep logs to your Vault.
  function shCoach() {
    var f = figment("Coach — form, not reps", "set");
    f.counters.reps = counter("reps", { hi: 99 });
    addScene(f, scene("set", {
      lines: [line("COACH", { row: 0, size: "sm", color: "accent_memory" }),
              line("{slot}", { row: 1, size: "lg", color: "accent_attention" }),
              line("clean reps: {count:reps}", { row: 3, size: "sm", color: "text_secondary" })],
      glyphs: _bar(0.5, 0.68, 0.16, "accent_attention"),
      on: { "text": { target: SELF },
            "single": { target: SELF, counter_ops: [inc("reps")], emit: "rep", record: true },
            "double": { target: END } },
    }));
    return f;
  }
  var SHOWCASES = {
    whisper: shWhisper, ask: shAsk, secondSight: shSecondSight, tethered: shTethered,
    threshold: shThreshold, ember: shEmber, coach: shCoach,
    headControl: shHeadControl, mandala: shMandala, world: shWorld,
    keep: shKeep, fusion: shFusion,
  };

  // -- Ask Juno (client fallback): a lightweight plain-English → figment map ---
  // When the page is served BY a Brain, "Ask Juno" POSTs to /dreamlayer/rc/compose
  // and the full offline IntentParser (intent_parser.py) runs there. On the static
  // landing page there is no Brain, so this keyword matcher picks a recipe and
  // pulls out durations — a useful subset, always budget-clean because it only
  // ever emits the vetted templates.
  function _dur(t, unit) {
    var m = t.match(new RegExp("(\\d+(?:\\.\\d+)?)\\s*(?:" + unit + ")"));
    return m ? +m[1] : null;
  }
  function composeLocal(prompt) {
    var t = String(prompt || "").toLowerCase().trim();
    if (!t) return { matched: false };
    var mins = _dur(t, "minute|min"), secs = _dur(t, "second|sec");
    var dur = mins ? mins * 60 : secs;   // seconds, if a length was named
    var has = function () { for (var i = 0; i < arguments.length; i++) if (t.indexOf(arguments[i]) >= 0) return true; return false; };
    // ordered matchers — most specific first. The stack showcases come first so
    // the wonder-features the tour promises are actually draftable from words.
    var M = [
      // -- the whole-stack showcases (need a paired Brain to feed live) --------
      { k: "whisper", kw: ["translat", "language", "spanish", "french", "japanese",
        "foreign", "menu", "subtitle", "interpret"], make: function () { return shWhisper(); } },
      { k: "ask", kw: ["ask", "answer", "question", "what's due", "when is my",
        "my brain", "recall", "look it up", "remind me what"], make: function () { return shAsk(); } },
      { k: "coach", kw: ["form", "posture", "squat depth", "my squat", "trainer",
        "coach my", "coach me", "technique"], make: function () { return shCoach(); } },
      { k: "secondSight", kw: ["what is this", "what am i looking", "identify",
        "name this", "name what", "what plant", "what wine", "landmark", "recognize"],
        make: function () { return shSecondSight(); } },
      { k: "tethered", kw: ["partner", "girlfriend", "boyfriend", "spouse", "wife",
        "husband", "long distance", "miss you", "thinking of", "presence", "when they're near",
        "loved one"], make: function () { return shTethered(); } },
      { k: "ember", kw: ["memory", "remember when", "anniversary", "years ago",
        "this spot", "where it happened", "resurface"], make: function () { return shEmber(); } },
      { k: "threshold", kw: ["when i get to", "when i arrive", "when i reach", "geofence",
        "at the gym start", "when i walk in", "when i enter", "place trigger"],
        make: function () { return shThreshold(); } },
      { k: "mandala", kw: ["mandala", "meditat", "calm", "zen", "grounding"],
        make: function () { return shMandala(); } },
      // -- the makeable-today recipes (work offline, no Brain) -----------------
      { k: "score", kw: ["score", "scoreboard", "keep score", " vs ", "point"],
        make: function () { return tScore({}); } },
      { k: "focus", kw: ["focus", "deep work", "pomodoro", "work session", "concentrate", "study"],
        make: function () { return tFocus({ minutes: mins || 25 }); } },
      { k: "interval", kw: ["interval", "hiit", "tabata"],
        make: function () { return tInterval({ work: dur || 180, rest: _restSec(t) || 30 }); } },
      { k: "breathing", kw: ["breath", "box breathing", "breathe"],
        make: function () { var b = dur || 4; return tBreathing({ in_s: b, hold_s: b, out_s: b }); } },
      // reps needs a word-ish boundary so "countdown"/"count down" don't hijack it
      { k: "reps", kw: ["rep", "push-up", "pushup", "sit-up", "situp", "squat",
        "pull-up", "pullup", "tally", "nod to count", "count my", "count reps"],
        make: function () { return tReps({ label: (t.match(/(push-?ups?|sit-?ups?|squats?|pull-?ups?|reps?)/) || [])[0] || "reps" }); } },
      { k: "checklist", kw: ["checklist", "to-do", "to do", "todo", "steps", "ritual",
        "routine", "then ", "reminder", "remind me", "medication", "meds", "pill",
        "stretch", "hydrate", "drink water", "skincare", "morning routine", "night routine"],
        make: function () {
          var steps = t.replace(/^.*?:/, "").split(/,|\bthen\b|;/).map(function (s) { return s.trim(); })
                       .filter(Boolean).map(function (s) { return s.slice(0, B.MAX_TEXT_LEN); });
          return tChecklist({ steps: steps.length ? steps.slice(0, B.MAX_SCENES) : undefined });
        } },
      { k: "countdown", kw: ["countdown", "count down", "timer", "count up", "stopwatch", "egg timer"],
        make: function () { return tCountdown({ seconds: dur || 300 }); } },
      // interval also matches the two-phase "work … rest" phrasing
      { k: "interval2", real: "interval", test: function () { return has("work") && has("rest"); },
        make: function () { return tInterval({ work: dur || 180, rest: _restSec(t) || 30 }); } },
    ];
    for (var i = 0; i < M.length; i++) {
      var m = M[i], hit = m.test ? m.test() : m.kw.some(function (w) { return t.indexOf(w) >= 0; });
      if (hit) return { matched: true, kind: m.real || m.k, figment: m.make() };
    }
    return { matched: false };
  }
  function _restSec(t) {
    var m = t.match(/(\d+(?:\.\d+)?)\s*(?:minute|min|second|sec)\s*(?:of\s*)?rest/) ||
            t.match(/rest\s*(?:of\s*|for\s*)?(\d+(?:\.\d+)?)\s*(?:minute|min|second|sec)/);
    if (!m) return null;
    return /min/.test(m[0]) ? +m[1] * 60 : +m[1];
  }

  // -- validation (a subset of budgets.verify — everything the builder emits) -
  // mirror reality_compiler/v2/figment._valid_event so a scene's `on` keys are
  // held to the same grammar the Python gate enforces (no false "safe").
  var BASE_EVENTS = ["single", "double", "long", "imu_tap", "text"];
  var IMU_GESTURES = ["nod", "shake", "peek", "tilt", "double_nod"];
  function validEvent(name) {
    if (BASE_EVENTS.indexOf(name) >= 0) return true;
    if (name.indexOf("ble:") === 0) { var c = name.slice(4); return /^\d+$/.test(c) && +c >= 0 && +c <= 255; }
    if (name.indexOf("imu:") === 0) return IMU_GESTURES.indexOf(name.slice(4)) >= 0;
    if (name.indexOf("place:") === 0) return name.slice(6) === "enter" || name.slice(6) === "exit";
    if (name.indexOf("bond:") === 0) { var r = name.slice(5); return r === "near" || (r.indexOf("tag:") === 0 && /^[a-z0-9]{1,16}$/i.test(r.slice(4))); }
    return false;
  }
  function timed(s) { return s.duration_sec != null; }
  function targets(s) {
    var out = [];
    (s.on_timeout || []).forEach(function (t) { out.push(t.target); });
    if (s.on) Object.keys(s.on).forEach(function (k) { out.push(s.on[k].target); });
    return out;
  }
  function validate(fig) {
    var v = [];
    function bad(code, msg, sid) { v.push({ code: code, msg: msg, scene: sid || null }); }
    if (!fig.name || fig.name.length > B.MAX_NAME_LEN) bad("name", "name must be 1.." + B.MAX_NAME_LEN + " chars");
    var ids = Object.keys(fig.scenes);
    if (ids.length === 0) bad("empty", "a lens needs at least one scene");
    if (ids.length > B.MAX_SCENES) bad("scene_count", ids.length + " scenes > max " + B.MAX_SCENES);
    if (Object.keys(fig.counters || {}).length > B.MAX_COUNTERS) bad("counter_count", "too many counters");
    var slotNames = _namedSlots(fig);
    if (slotNames.length > B.MAX_SLOTS) bad("slot_count", slotNames.length + " named slots > max " + B.MAX_SLOTS);
    slotNames.forEach(function (n) { if (n.length > B.MAX_NAME_LEN) bad("slot_name", "slot name too long"); });
    if (ids.length && ids.indexOf(fig.initial) < 0) bad("initial", "start scene '" + fig.initial + "' doesn't exist");
    // Refuse the two glass-grammar features the browser engine (Stage) does not
    // model, so "valid here" strictly means "the preview/verifier runs it exactly
    // as the glasses would". The no-code builder never emits these; this only
    // guards a hand-crafted or Python-authored share code from being previewed,
    // shared, or golf-verified against a simulation that would silently differ.
    if (fig.battery_below != null) bad("unsupported", "battery-triggered lenses aren't supported in the browser lens engine");
    ids.forEach(function (sid) {
      var s = fig.scenes[sid];
      if (s.duration_range) bad("unsupported", "random-timer (duration_range) scenes aren't supported in the browser lens engine", sid);
      if ((s.lines || []).length > B.MAX_LINES) bad("lines", s.lines.length + " lines > max " + B.MAX_LINES, sid);
      var rows = {};
      (s.lines || []).forEach(function (ln) {
        if ((ln.content || "").length > B.MAX_TEXT_LEN) bad("text_len", "a line is > " + B.MAX_TEXT_LEN + " chars", sid);
        if (ln.row < 0 || ln.row >= B.MAX_LINES) bad("row", "row " + ln.row + " out of range", sid);
        if (rows[ln.row]) bad("row", "two lines on row " + ln.row, sid); rows[ln.row] = 1;
        if (COLORS.indexOf(ln.color) < 0) bad("color", "'" + ln.color + "' is not a palette color", sid);
        if (SIZES.indexOf(ln.size) < 0) bad("size", "unknown size '" + ln.size + "'", sid);
      });
      if (timed(s) && !(s.duration_sec >= B.MIN_SCENE_SEC && s.duration_sec <= B.MAX_SCENE_SEC))
        bad("duration", "duration must be " + B.MIN_SCENE_SEC + ".." + B.MAX_SCENE_SEC + "s", sid);
      if (timed(s) && !(s.on_timeout && s.on_timeout.length)) bad("timeout", "a timed scene needs a 'when it ends' step", sid);
      if (!timed(s) && s.on_timeout && s.on_timeout.length) bad("timeout", "on-timeout needs a duration", sid);
      if (s.tick === "countdown" && !timed(s)) bad("tick", "a countdown needs a duration", sid);
      if (s.on_timeout && s.on_timeout.length > B.MAX_BRANCHES) bad("branches", "too many timeout branches", sid);
      targets(s).forEach(function (tg) {
        if (tg !== END && tg !== SELF && ids.indexOf(tg) < 0) bad("target", "goes to unknown scene '" + tg + "'", sid);
      });
      if (s.on) Object.keys(s.on).forEach(function (ev) {
        if (!validEvent(ev)) bad("event", "'" + ev + "' is not a trigger the glasses know", sid);
      });
      // per-transition budget (mirror budgets.verify.check_transition): counter
      // op count + declared-counter/emit-tag/guard checks, so "valid here" means
      // the same thing the on-glass proof means, not a looser subset.
      function checkTrans(t, isTimeout) {
        if ((t.counter_ops || []).length > B.MAX_COUNTER_OPS) bad("counter_ops", (t.counter_ops.length) + " counter ops > max " + B.MAX_COUNTER_OPS, sid);
        (t.counter_ops || []).forEach(function (op) {
          if (!fig.counters || !fig.counters[op.counter]) bad("counter", "op on undeclared counter '" + op.counter + "'", sid);
          if (["inc", "dec", "set"].indexOf(op.op) < 0) bad("counter", "unknown counter op '" + op.op + "'", sid);
        });
        if (t.emit != null && (!t.emit || String(t.emit).length > B.MAX_EMIT_TAG_LEN)) bad("emit_tag", "emit tag must be 1.." + B.MAX_EMIT_TAG_LEN + " chars", sid);
        if (t.when != null) {
          if (!isTimeout) bad("guard", "guards are only allowed on 'when it ends' steps", sid);
          else if (!fig.counters || !fig.counters[t.when.counter]) bad("guard", "guard on undeclared counter '" + t.when.counter + "'", sid);
          else if (["ge", "le", "eq"].indexOf(t.when.cmp) < 0) bad("guard", "unknown comparison '" + t.when.cmp + "'", sid);
        }
      }
      (s.on_timeout || []).forEach(function (t) { checkTrans(t, true); });
      if (s.on) Object.keys(s.on).forEach(function (ev) { checkTrans(s.on[ev], false); });
      if (s.pulse) {
        if (!timed(s)) bad("pulse", "pulse needs a timed scene", sid);
        if (!(s.pulse.rate_hz > 0 && s.pulse.rate_hz <= B.MAX_PULSE_HZ)) bad("pulse_rate", "pulse > " + B.MAX_PULSE_HZ + "Hz (the photic-safety cap)", sid);
        if (timed(s) && s.pulse.window_sec > s.duration_sec) bad("pulse", "pulse window exceeds the scene", sid);
        if (COLORS.indexOf(s.pulse.color) < 0) bad("color", "pulse color is not a token", sid);
      }
      // painted strokes: mirror budgets.verify's paint-layer caps exactly
      if (s.glyphs) {
        if (s.glyphs.length > B.MAX_GLYPHS) bad("glyphs", s.glyphs.length + " strokes > max " + B.MAX_GLYPHS, sid);
        s.glyphs.forEach(function (g, gi) {
          var pts = g.points || [];
          if (!(pts.length >= 2 && pts.length <= B.MAX_GLYPH_POINTS)) bad("glyph_points", "stroke " + gi + " needs 2.." + B.MAX_GLYPH_POINTS + " points", sid);
          for (var k = 0; k < pts.length; k++) {
            if (!(pts[k][0] >= 0 && pts[k][0] <= 1 && pts[k][1] >= 0 && pts[k][1] <= 1)) { bad("glyph_coord", "stroke " + gi + " leaves the display", sid); break; }
          }
          if (COLORS.indexOf(g.color) < 0) bad("color", "stroke " + gi + " color is not a token", sid);
          if (SIZES.indexOf(g.width) < 0) bad("glyph_width", "stroke " + gi + " width unknown", sid);
        });
      }
    });
    return { ok: v.length === 0, violations: v };
  }

  // -- the proof, as a consent card (mirrors reality_compiler/v2/safety.py) ---
  function safetyCard(fig) {
    var rep = validate(fig);
    var worstHz = 0, longest = 0, sceneCount = Object.keys(fig.scenes).length;
    Object.keys(fig.scenes).forEach(function (sid) {
      var s = fig.scenes[sid];
      if (s.pulse) worstHz = Math.max(worstHz, s.pulse.rate_hz);
      if (timed(s)) longest = Math.max(longest, s.duration_sec);
    });
    return {
      ok: rep.ok,
      violations: rep.violations,
      cannot: [
        "flash faster than " + B.MAX_PULSE_HZ + " times a second — the eye-safety cap (this one: ≤ " + (worstHz || 0) + ")",
        "reach the internet, your files, the camera, or the mic — it's data, not code",
        "show more than " + B.MAX_LINES + " lines at once",
        "block your exit — a press-and-hold always dismisses any lens",
      ],
      will: [sceneCount + " screen(s), each held at least half a second"],
    };
  }

  // stable stringify — sorted keys at every level (a replacer *array* would
  // wrongly act as an allow-list at every depth and drop nested scene fields).
  function canonical(fig) {
    return JSON.stringify(fig, function (k, v) {
      if (v && typeof v === "object" && !Array.isArray(v)) {
        var out = {}; Object.keys(v).sort().forEach(function (kk) { out[kk] = v[kk]; }); return out;
      }
      return v;
    });
  }

  // -- shareable lenses: a whole lens fits in a URL --------------------------
  // A figment is small, signed-*able* data, so a lens travels as a link (and a
  // QR). Anyone who opens it gets the lens live in the builder to remix — and
  // their glasses re-prove it before it ever runs, so a share carries zero
  // trust. UTF-8 → base64url, no server, no account.
  function _b64urlEncode(str) {
    var b64 = (typeof btoa !== "undefined")
      ? btoa(unescape(encodeURIComponent(str)))
      : Buffer.from(str, "utf-8").toString("base64");
    return b64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }
  function _b64urlDecode(s) {
    var b64 = String(s).replace(/-/g, "+").replace(/_/g, "/");
    while (b64.length % 4) b64 += "=";
    return (typeof atob !== "undefined")
      ? decodeURIComponent(escape(atob(b64)))
      : Buffer.from(b64, "base64").toString("utf-8");
  }
  function encodeShare(fig, meta) {
    meta = meta || {};
    var f = JSON.parse(canonical(fig));
    if (f.id === "") delete f.id;                // the builder mints identity on import
    var payload = { v: 1, f: f };
    if (meta.author) payload.a = String(meta.author).slice(0, 40);
    return _b64urlEncode(JSON.stringify(payload));
  }
  function decodeShare(code) {
    try {
      var p = JSON.parse(_b64urlDecode(code));
      if (!p || !p.f || typeof p.f !== "object") return null;
      var fig = p.f; if (!fig.scenes || !Object.keys(fig.scenes).length) return null;
      if (!fig.name) fig.name = "Shared lens";
      if (fig.id == null) fig.id = "";
      if (!validate(fig).ok) return null;        // never load a lens that isn't safe
      return { figment: fig, author: (p.a || "") };
    } catch (e) { return null; }
  }
  // Figment Golf: the same lens in fewer bytes is the whole game. `bytes` is the
  // canonical UTF-8 size; `moves` is how much machine you packed into them.
  function golfScore(fig) {
    var c = canonical(fig);
    var bytes = (typeof TextEncoder !== "undefined") ? new TextEncoder().encode(c).length
      : (typeof Buffer !== "undefined" ? Buffer.byteLength(c, "utf8") : c.length);
    var ids = Object.keys(fig.scenes || {}), moves = 0;
    ids.forEach(function (id) {
      var s = fig.scenes[id];
      moves += (s.lines || []).length + (s.glyphs || []).length;
      moves += (s.on ? Object.keys(s.on).length : 0) + (s.on_timeout || []).length;
      if (s.pulse) moves += 1; if (s.cadence) moves += 1; if (s.tick) moves += 1;
    });
    moves += Object.keys(fig.counters || {}).length;
    return { bytes: bytes, moves: moves, scenes: ids.length,
             valid: validate(fig).ok };
  }

  // -- reference interpreter (the JS twin of reality_compiler/v2/interpreter.py
  // and halo-lua/app/figment_stage.lua). Faithful enough that Figment Golf can
  // *verify* a submission actually solves a challenge — not merely parses — and
  // the registry re-runs the exact same check server-side. Parity with the
  // Python Stage is pinned by tests/test_lens_builder.py. -----------------------
  var EMIT_BURST = 5, EMIT_REFILL_PER_S = 1.0;
  function _fmtClock(secs) {
    secs = Math.max(0, Math.ceil(secs));
    return secs >= 60 ? (Math.floor(secs / 60) + ":" + ("0" + (secs % 60)).slice(-2)) : String(secs);
  }
  function Stage(fig) {
    this.fig = fig;
    this.counters = {};
    var cs = fig.counters || {};
    Object.keys(cs).forEach((function (n) { this.counters[n] = cs[n].start || 0; }).bind(this));
    this.slots = { "": "" }; this.emits = []; this.recorded = []; this.dropped = 0;
    this.ended = false; this.clock = 0; this._tokens = EMIT_BURST;
    this.scene_elapsed = 0; this._lastElapsed = 0;
    this._enter(fig.initial);
  }
  Stage.prototype._scene = function () { return this.fig.scenes[this.current]; };
  Stage.prototype._enter = function (id) {
    this._lastElapsed = this.scene_elapsed || 0;
    this.current = id; this.scene_elapsed = 0;
    var s = this._scene();
    this._duration = (s && s.duration_sec != null) ? s.duration_sec : null;   // no rng scenes in the builder
  };
  Stage.prototype._end = function () { this._lastElapsed = this.scene_elapsed; this.ended = true; };
  Stage.prototype.step = function (dt) {
    if (dt == null) dt = 1.0;
    if (this.ended) return this;
    var left = dt;
    while (left > 1e-9 && !this.ended) {
      if (this._duration == null) { this._advance(left); break; }
      var rem = this._duration - this.scene_elapsed;
      if (left < rem - 1e-9) { this._advance(left); break; }
      this._advance(rem); left -= rem; this._timeout();
    }
    return this;
  };
  Stage.prototype._advance = function (dt) {
    this.clock += dt; this.scene_elapsed += dt;
    this._tokens = Math.min(EMIT_BURST, this._tokens + dt * EMIT_REFILL_PER_S);
  };
  Stage.prototype.inject = function (event, text) {
    if (this.ended) return false;
    if (event === "text" || event.indexOf("text:") === 0) {
      var name = event.indexOf("text:") === 0 ? event.slice(5) : "";
      if (text != null) {
        var named = Object.keys(this.slots).filter(function (k) { return k; });
        if (name === "" || this.slots[name] != null || named.length < B.MAX_SLOTS)
          this.slots[name] = String(text).slice(0, B.MAX_TEXT_LEN);
      }
      return this._dispatch("text");
    }
    return this._dispatch(event);
  };
  Stage.prototype._dispatch = function (event) {
    var on = this._scene().on || {}, t = on[event];
    if (t == null && event.indexOf("ble:") === 0) t = on.ble;
    if (t == null) return false;
    this._take(t); return true;
  };
  Stage.prototype._timeout = function () {
    var ot = this._scene().on_timeout || [];
    for (var i = 0; i < ot.length; i++) {
      if (ot[i].when == null || this._guard(ot[i])) { this._take(ot[i]); return; }
    }
    this._end();
  };
  Stage.prototype._guard = function (t) {
    var g = t.when, v = this.counters[g.counter] || 0;
    if (g.cmp === "ge") return v >= g.value;
    if (g.cmp === "le") return v <= g.value;
    return v === g.value;
  };
  Stage.prototype._take = function (t) {
    var self = this;
    (t.counter_ops || []).forEach(function (op) {
      var d = self.fig.counters[op.counter]; if (!d) return;
      var cur = self.counters[op.counter] || 0;
      if (op.op === "inc") cur += op.amount; else if (op.op === "dec") cur -= op.amount; else cur = op.amount;
      self.counters[op.counter] = Math.max(d.lo == null ? 0 : d.lo, Math.min(d.hi == null ? B.COUNTER_HI : d.hi, cur));
    });
    if (t.emit != null) {
      if (this._tokens >= 1.0) { this._tokens -= 1.0; this.emits.push([this.clock, t.emit]);
        if (t.record) this.recorded.push([this.clock, t.emit]); }
      else this.dropped += 1;
    }
    if (t.target === END) this._end();
    else if (t.target === SELF) this._enter(this.current);
    else if (this.fig.scenes[t.target]) this._enter(t.target);
    else this._end();
  };
  Stage.prototype.remaining = function () {
    return this._duration == null ? 0 : Math.max(0, this._duration - this.scene_elapsed);
  };
  Stage.prototype._resolve = function (content) {
    var s = this._scene(), self = this;
    var el = s.tick ? this.scene_elapsed : this._lastElapsed;
    var out = String(content)
      .replace(/\{remaining\}/g, _fmtClock(this.remaining()))
      .replace(/\{remaining_s\}/g, String(Math.ceil(this.remaining())))
      .replace(/\{elapsed\}/g, _fmtClock(el))
      .replace(/\{elapsed_ms\}/g, String(Math.floor(el * 1000)))
      .replace(/\{slot\}/g, this.slots[""] || "")
      .replace(SLOT_TOKEN_RE, function (_, n) { return self.slots[n] != null ? self.slots[n] : ""; })
      .replace(/\{count:(\w+)\}/g, function (_, n) { return String(self.counters[n] != null ? self.counters[n] : 0); });
    return out.slice(0, B.MAX_TEXT_LEN);
  };
  Stage.prototype._cadence = function () {
    var cad = this._scene().cadence;
    if (!cad) return { phase: "", level: 0 };
    var period = (cad.in_s || 0) + (cad.hold_s || 0) + (cad.out_s || 0);
    if (period <= 0) return { phase: "", level: 0 };
    var u = this.scene_elapsed % period, r3 = function (x) { return Math.round(x * 1000) / 1000; };
    if (u < cad.in_s) return { phase: "in", level: r3(cad.in_s ? u / cad.in_s : 1) };
    if (u < cad.in_s + cad.hold_s) return { phase: "hold", level: 1 };
    var out = u - cad.in_s - cad.hold_s;
    return { phase: "out", level: r3(1 - (cad.out_s ? out / cad.out_s : 1)) };
  };
  Stage.prototype.frame = function () {
    if (this.ended) return { scene: END, ended: true, lines: [], pulse_on: false, cadence_phase: "", cadence_level: 0 };
    var s = this._scene(), self = this, pulse_on = false, pulse_color = null;
    if (s.pulse && this._duration != null && this.remaining() <= s.pulse.window_sec) {
      pulse_on = (Math.floor(this.scene_elapsed * s.pulse.rate_hz * 2) % 2) === 0;
      pulse_color = s.pulse.color;
    }
    var cad = this._cadence();
    return {
      scene: this.current, ended: false,
      lines: (s.lines || []).map(function (ln) {
        return { text: self._resolve(ln.content), row: ln.row, size: ln.size, color: ln.color }; }),
      glyphs: (s.glyphs || []).slice(),
      pulse_on: pulse_on, pulse_color: pulse_color,
      cadence_phase: cad.phase, cadence_level: cad.level,
    };
  };

  // -- Figment Golf: verified challenges ---------------------------------------
  // A challenge is a *brief* plus a machine-checkable acceptance spec: fresh
  // Stages driven through scripted scenarios, each asserting an observable
  // outcome. "Solving" it means the exact behavior — so the leaderboard ranks
  // genuine skill (fewest bytes that still pass), not popularity. `par` is a
  // clean reference solution's byte count; beat it and you're under par.
  function _lineText(fr) { return (fr.lines || []).map(function (l) { return l.text; }).join(" • "); }
  function _runScenario(fig, sc) {
    var st = new Stage(fig), fail = null;
    (sc.ops || []).forEach(function (op) {
      if (op[0] === "step") st.step(op[1]);
      else if (op[0] === "tap") st.inject("single");
      else if (op[0] === "inject") st.inject(op[1], op[2]);
      else if (op[0] === "text") st.inject("text", op[1]);
    });
    var e = sc.expect || {}, fr = st.frame();
    function bad(m) { if (!fail) fail = m; }
    if (e.ended != null && !!fr.ended !== !!e.ended) bad(e.ended ? "should have ended" : "should still be running");
    if (e.scene != null && st.current !== e.scene && !fr.ended) bad("expected scene “" + e.scene + "”, was “" + st.current + "”");
    if (e.lineHas != null && _lineText(fr).toLowerCase().indexOf(String(e.lineHas).toLowerCase()) < 0)
      bad("expected the glass to show “" + e.lineHas + "”");
    if (e.lineLacks != null && _lineText(fr).toLowerCase().indexOf(String(e.lineLacks).toLowerCase()) >= 0)
      bad("the glass must not show “" + e.lineLacks + "” yet");
    if (e.count != null) Object.keys(e.count).forEach(function (n) {
      if ((st.counters[n] || 0) !== e.count[n]) bad(n + " should be " + e.count[n] + " (was " + (st.counters[n] || 0) + ")"); });
    if (e.remainingLe != null && st.remaining() > e.remainingLe + 1e-6) bad("timer runs too long");
    if (e.remainingGe != null && st.remaining() < e.remainingGe - 1e-6) bad("timer is too short");
    if (e.pulse != null && !!fr.pulse_on !== !!e.pulse) bad(e.pulse ? "should be pulsing now" : "should not be pulsing yet");
    return { ok: fail == null, why: fail, label: sc.label || "" };
  }
  function runChallenge(fig, ch) {
    var g = golfScore(fig), results = (ch.checks || []).map(function (sc) { return _runScenario(fig, sc); });
    var passed = g.valid && results.every(function (r) { return r.ok; });
    return { solved: passed, valid: g.valid, bytes: g.bytes, moves: g.moves, scenes: g.scenes,
             par: ch.par || 0, underPar: passed && ch.par ? (ch.par - g.bytes) : 0,
             checks: results };
  }

  // The launch challenges. Each brief is unambiguous and every acceptance check
  // is a behavior, never a shape — so a solver is rewarded for expressing the
  // exact thing in fewer bytes, nothing else.
  var GOLF = [
    { id: "pocket-timer", title: "Pocket timer", icon: "timer",
      brief: "A silent 3-minute timer that counts down and ends on its own. Show the time remaining. No taps, no extras.",
      par: 270,
      checks: [
        { label: "opens at 3:00 on the glass", ops: [], expect: { remainingGe: 180, remainingLe: 180, ended: false, lineHas: "3:00" } },
        // the display must actually count down — a static "3:00" label reads
        // "3:00" here, not "2:00", so only a real {remaining} lens passes
        { label: "reads 2:00 a minute in", ops: [["step", 60]], expect: { ended: false, lineHas: "2:00" } },
        { label: "still running at 2:59", ops: [["step", 179]], expect: { ended: false } },
        { label: "ends by 3:00", ops: [["step", 180]], expect: { ended: true } },
      ] },
    { id: "last-30", title: "The last 30", icon: "pulse",
      brief: "A 2-minute focus timer that pulses in its final 30 seconds, then ends. The pulse must be off before the last 30s and on inside it.",
      par: 340,
      checks: [
        { label: "shows 2:00 at the start", ops: [], expect: { lineHas: "2:00", ended: false } },
        { label: "no pulse at 1:00 in", ops: [["step", 60]], expect: { ended: false, pulse: false } },
        { label: "pulsing at 1:40 in", ops: [["step", 100]], expect: { ended: false, pulse: true } },
        { label: "ends by 2:00", ops: [["step", 120]], expect: { ended: true } },
      ] },
    { id: "tally", title: "Two-sided tally", icon: "score",
      brief: "A scoreboard: tap for US, double-tap for THEM, press-and-hold to reset both to zero. Show both running scores.",
      par: 620,
      checks: [
        { label: "two taps make US = 2", ops: [["inject", "single"], ["inject", "single"]], expect: { count: { us: 2 } } },
        { label: "a double-tap makes THEM = 1", ops: [["inject", "double"]], expect: { count: { them: 1 } } },
        { label: "the score shows on the glass", ops: [["inject", "single"]], expect: { lineHas: "1" } },
        { label: "hold resets both to zero", ops: [["inject", "single"], ["inject", "double"], ["inject", "long"]],
          expect: { count: { us: 0, them: 0 } } },
      ] },
    { id: "streak", title: "Nod streak", icon: "nod",
      brief: "Count clean nods. Each nod adds one and shows the running total; a head-shake resets to zero. Runs until you look away (a long press ends it).",
      par: 450,
      checks: [
        { label: "three nods make the count 3", ops: [["inject", "imu:nod"], ["inject", "imu:nod"], ["inject", "imu:nod"]],
          expect: { count: { n: 3 }, lineHas: "3" } },
        { label: "a shake resets to zero", ops: [["inject", "imu:nod"], ["inject", "imu:shake"]], expect: { count: { n: 0 } } },
        { label: "a long press ends it", ops: [["inject", "imu:nod"], ["inject", "long"]], expect: { ended: true } },
      ] },
  ];

  // -- scene-graph editing (the advanced editor) -----------------------------
  // the triggers a scene can listen for; "timeout" is the timed exit, the rest
  // are physical/gesture events (see figment_stage.lua on_event).
  // The things a scene can wait for, in plain words. `timeout` is the timed
  // exit; the rest are gestures, world signals, or a line of text from your
  // Brain (see reality_compiler/v2/figment._valid_event + figment_stage.lua).
  // `hint` powers the builder's inline help so a newcomer knows what each means.
  var TRIGGERS = [
    { key: "timeout",     label: "the countdown ends",   hint: "when this screen's timer runs out" },
    { key: "single",      label: "tap",                  hint: "one tap on the temple of the glasses" },
    { key: "double",      label: "double-tap",           hint: "two quick taps" },
    { key: "long",        label: "press & hold",         hint: "press and hold on the temple" },
    { key: "imu:nod",     label: "nod your head",        hint: "a clear up-down nod" },
    { key: "imu:shake",   label: "shake your head",      hint: "a left-right shake — good for 'no' / go back" },
    { key: "imu:peek",    label: "glance up",            hint: "flick your eyes/head up" },
    { key: "place:enter", label: "you arrive somewhere", hint: "reach a place your Brain knows (geofence)" },
    { key: "place:exit",  label: "you leave a place",    hint: "step away from a known place" },
    { key: "bond:near",   label: "a loved one is near",  hint: "a bonded partner comes close" },
    { key: "ble:3",       label: "a button is pressed",  hint: "a $6 wireless button out in the world" },
    { key: "text",        label: "your Brain sends text",hint: "the Brain streams a line into {slot} (a translation, an answer)" },
  ];
  function emptyFigment() {
    var f = figment("My lens", "s0");
    addScene(f, scene("s0", { duration_sec: 10, tick: "countdown",
      lines: [line("HELLO", { row: 0, size: "lg", color: "accent_memory" })],
      on_timeout: [{ target: END }] }));
    return f;
  }
  function newSceneId(fig) {
    var i = 0; while (fig.scenes["s" + i]) i++; return "s" + i;
  }
  function addBlankScene(fig, id) {
    id = id || newSceneId(fig);
    return addScene(fig, scene(id, { lines: [line("New scene")], on: {} }));
  }
  function deleteScene(fig, id) {
    if (!fig.scenes[id]) return;
    delete fig.scenes[id];
    // any transition that pointed here now ends instead of dangling
    Object.keys(fig.scenes).forEach(function (sid) {
      var s = fig.scenes[sid];
      (s.on_timeout || []).forEach(function (t) { if (t.target === id) t.target = END; });
      if (s.on) Object.keys(s.on).forEach(function (k) { if (s.on[k].target === id) s.on[k].target = END; });
    });
    if (fig.initial === id) fig.initial = Object.keys(fig.scenes)[0] || "";
  }
  // changing a transition's target/trigger in the editor must NOT wipe the
  // counter/emit/record/guard behaviour it carries — merge, don't replace.
  function setTransition(scene_, trigger, target) {
    if (trigger === "timeout") {
      var prev = (scene_.on_timeout && scene_.on_timeout[scene_.on_timeout.length - 1]) || {};
      scene_.on_timeout = [_assign({}, prev, { target: target })];
    } else {
      scene_.on = scene_.on || {};
      scene_.on[trigger] = _assign({}, scene_.on[trigger] || {}, { target: target });
    }
  }
  function _assign(dst) {
    for (var i = 1; i < arguments.length; i++) { var s = arguments[i]; for (var k in s) if (s.hasOwnProperty(k)) dst[k] = s[k]; }
    return dst;
  }
  function removeTransition(scene_, trigger) {
    if (trigger === "timeout") { delete scene_.on_timeout; }
    else if (scene_.on) { delete scene_.on[trigger]; }
  }
  // each entry carries what the transition *does* beyond navigating, so the
  // editor can show it (a rep counter's "+1", a "sends ask", a guarded branch)
  function _extras(t) { return { ops: t.counter_ops || [], emit: (t.emit == null ? null : t.emit), record: !!t.record, when: t.when || null }; }
  function listTransitions(scene_) {
    var out = [];
    (scene_.on_timeout || []).forEach(function (t) { out.push(_assign({ trigger: "timeout", target: t.target }, _extras(t))); });
    if (scene_.on) Object.keys(scene_.on).forEach(function (k) { out.push(_assign({ trigger: k, target: scene_.on[k].target }, _extras(scene_.on[k]))); });
    return out;
  }
  function graphEdges(fig) {
    var edges = [];
    Object.keys(fig.scenes).forEach(function (sid) {
      listTransitions(fig.scenes[sid]).forEach(function (t) {
        edges.push({ from: sid, trigger: t.trigger, to: t.target });
      });
    });
    return edges;
  }

  // -- a store listing (the Publish flow, INNOVATION_SESSION 5.2) -------------
  // canonical figment + the proof + author metadata. The registry re-checks the
  // proof; the listing's claims are recomputed, never trusted.
  function listing(fig, meta) {
    meta = meta || {};
    var card = safetyCard(fig);
    return {
      kind: "figment-listing", v: 1,
      figment: fig,
      name: (meta.name || fig.name || "Untitled").slice(0, 40),
      author: (meta.author || "").slice(0, 40),
      description: (meta.description || "").slice(0, 240),
      forwho: (meta.forwho || "").slice(0, 120),
      price: 0,                         // free; a paid tier is reserved (MARKETPLACE.md)
      proof: {
        ok: card.ok,
        scenes: Object.keys(fig.scenes).length,
        cannot: card.cannot,
      },
    };
  }

  return {
    BUDGETS: B, COLORS: COLORS, SIZES: SIZES, HEX: HEX, END: END, SELF: SELF,
    TRIGGERS: TRIGGERS, TEMPLATES: TEMPLATES,
    composeLocal: composeLocal,
    figment: figment, scene: scene, line: line, glyph: glyph, addScene: addScene,
    emptyFigment: emptyFigment, addBlankScene: addBlankScene, deleteScene: deleteScene,
    newSceneId: newSceneId, setTransition: setTransition, removeTransition: removeTransition,
    listTransitions: listTransitions, graphEdges: graphEdges,
    validate: validate, safetyCard: safetyCard, canonical: canonical, listing: listing,
    encodeShare: encodeShare, decodeShare: decodeShare, golfScore: golfScore,
    Stage: Stage, runChallenge: runChallenge, GOLF: GOLF,
    templates: { reps: tReps, focus: tFocus, score: tScore, breathing: tBreathing,
      interval: tInterval, countdown: tCountdown, checklist: tChecklist },
    showcases: SHOWCASES,
  };
});
