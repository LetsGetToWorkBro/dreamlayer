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
  };
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
    return { name: name, start: o.start || 0, lo: o.lo || 0, hi: o.hi == null ? 999 : o.hi };
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
      lines: [line("BREATHE", { row: 0, size: "md", color: "text_secondary" })],
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

  // Whisper — read/hear any language, live. Camera OCR + mic → Brain/cloud
  // translate → the words stream onto {slot}.
  function shWhisper() {
    var f = figment("Whisper — live translate", "live");
    addScene(f, scene("live", {
      lines: [line("{slot}", { row: 1, size: "md", color: "text_primary" }),
              line("▸ translating live", { row: 4, size: "sm", color: "accent_memory" })],
      glyphs: [glyph([[0.18, 0.8], [0.34, 0.8]], { color: "accent_memory", width: "sm" }),
               glyph([[0.66, 0.8], [0.82, 0.8]], { color: "accent_memory", width: "sm" })],
      on: { "text": { target: SELF }, "double": { target: END } },
    }));
    return f;
  }
  // Ask — your Brain, on glass. Double-tap & speak → emit "ask" → the Brain
  // answers from your own memory (or cloud) → the answer lands in {slot}.
  function shAsk() {
    var f = figment("Ask — your Brain, on glass", "idle");
    addScene(f, scene("idle", {
      lines: [line("ASK ME ANYTHING", { row: 1, size: "md", color: "text_secondary" }),
              line("double-tap · then speak", { row: 3, size: "sm", color: "text_secondary" })],
      on: { "double": { target: "hear", emit: "ask" } },
    }));
    addScene(f, scene("hear", {
      duration_sec: 2, tick: "countup",
      lines: [line("listening…", { row: 1, size: "md", color: "accent_attention" })],
      pulse: { window_sec: 2, rate_hz: 1.5, color: "accent_attention" },
      on_timeout: [{ target: "answer" }], on: { "text": { target: "answer" }, "double": { target: "idle" } },
    }));
    addScene(f, scene("answer", {
      lines: [line("{slot}", { row: 1, size: "md", color: "text_primary" }),
              line("⛨ from your memory", { row: 4, size: "sm", color: "accent_memory" })],
      on: { "text": { target: SELF }, "double": { target: "idle" } },
    }));
    return f;
  }
  // Tethered — feel a bonded partner across the world. Their presence fires
  // bond:near, their mood-weather tints the ring, you emit a heartbeat back.
  function shTethered() {
    var f = figment("Tethered — feel them near", "away");
    addScene(f, scene("away", {
      lines: [line("· · ·", { row: 1, size: "lg", color: "text_secondary" }),
              line("2,400 miles away", { row: 4, size: "sm", color: "text_secondary" })],
      glyphs: _heartGlyph("border_subtle"), cadence: { in_s: 4, hold_s: 1, out_s: 4 },
      on: { "bond:near": { target: "near" }, "text": { target: SELF }, "double": { target: END } },
    }));
    addScene(f, scene("near", {
      duration_sec: 6, tick: "countdown",
      lines: [line("SHE'S NEAR", { row: 1, size: "lg", color: "accent_memory" })],
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
      lines: [line("HOME", { row: 0, size: "md", color: "text_secondary" }),
              line("walk somewhere…", { row: 4, size: "sm", color: "text_secondary" })],
      on: { "place:enter": { target: "gym" }, "double": { target: END } },
    }));
    addScene(f, scene("gym", {
      duration_sec: 5, tick: "countdown",
      lines: [line("GYM ✦ ROUND 1", { row: 1, size: "lg", color: "accent_attention" })],
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
      lines: [line("GLANCE + HOLD", { row: 1, size: "md", color: "text_secondary" }),
              line("to name what you see", { row: 3, size: "sm", color: "text_secondary" })],
      glyphs: [glyph(_ring(0.5, 0.42, 0.13), { color: "accent_memory", width: "sm" })],
      on: { "long": { target: "seen", emit: "look" }, "double": { target: END } },
    }));
    addScene(f, scene("seen", {
      lines: [line("{slot}", { row: 1, size: "md", color: "accent_success" }),
              line("hold to look again ↻", { row: 4, size: "sm", color: "text_secondary" })],
      on: { "text": { target: SELF }, "long": { target: "look" }, "double": { target: END } },
    }));
    return f;
  }
  // Ember — your own memory, handed back at the perfect moment. Standing where
  // it happened (place:enter) the Vault surfaces a line into {slot}.
  function shEmber() {
    var f = figment("Ember — memory, returned", "quiet");
    addScene(f, scene("quiet", {
      lines: [line("· here ·", { row: 1, size: "md", color: "text_secondary" })],
      on: { "place:enter": { target: "back" }, "text": { target: "back" }, "double": { target: END } },
    }));
    addScene(f, scene("back", {
      lines: [line("{slot}", { row: 1, size: "md", color: "accent_memory" })],
      glyphs: [glyph([[0.5, 0.72], [0.44, 0.6], [0.5, 0.5], [0.56, 0.6], [0.5, 0.72]], { color: "accent_attention", width: "sm" })],
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
      lines: [line("{slot}", { row: 0, size: "lg", color: "accent_attention" }),
              line("clean reps: {count:reps}", { row: 4, size: "sm", color: "text_secondary" })],
      glyphs: [glyph([[0.24, 0.62], [0.5, 0.62]], { color: "accent_attention", width: "lg" })],
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
    var has = function () { for (var i = 0; i < arguments.length; i++) if (t.indexOf(arguments[i]) >= 0) return true; return false; };
    var fig, kind;
    if (has("score", "scoreboard", "keep score", " vs ", "point")) {
      fig = tScore({}); kind = "score";
    } else if (has("rep", "count", "tally", "push-up", "pushup", "sit-up", "situp",
                   "squat", "pull-up", "pullup", "nod to")) {
      fig = tReps({ label: (t.match(/(push-?ups?|sit-?ups?|squats?|pull-?ups?|reps?)/) || [])[0] || "reps" });
      kind = "reps";
    } else if (has("focus", "deep work", "pomodoro", "work session", "concentrate", "study")) {
      fig = tFocus({ minutes: mins || 25 }); kind = "focus";
    } else if (has("interval", "hiit", "tabata") || (has("work") && has("rest"))) {
      fig = tInterval({ work: (mins ? mins * 60 : secs) || 180, rest: 30 }); kind = "interval";
    } else if (has("breath", "box breathing")) {
      var b = secs || 4; fig = tBreathing({ in_s: b, hold_s: b, out_s: b }); kind = "breathing";
    } else if (has("checklist", "steps", "ritual", "routine", "then ")) {
      var steps = t.replace(/^.*?:/, "").split(/,|\bthen\b|;/).map(function (s) { return s.trim(); })
                   .filter(Boolean).map(function (s) { return s.slice(0, B.MAX_TEXT_LEN); });
      fig = tChecklist({ steps: steps.length ? steps.slice(0, B.MAX_SCENES) : undefined }); kind = "checklist";
    } else if (has("countdown", "count down", "timer", "count up", "stopwatch")) {
      fig = tCountdown({ seconds: (mins ? mins * 60 : secs) || 300 }); kind = "countdown";
    } else {
      return { matched: false };
    }
    return { matched: true, kind: kind, figment: fig };
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
    if (ids.length && ids.indexOf(fig.initial) < 0) bad("initial", "start scene '" + fig.initial + "' doesn't exist");
    ids.forEach(function (sid) {
      var s = fig.scenes[sid];
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
        "pulse faster than " + B.MAX_PULSE_HZ + " Hz — the photic-safety cap (this one: ≤ " + (worstHz || 0) + " Hz)",
        "reach the network, your files, the camera, or the mic — it is data, not code",
        "show more than " + B.MAX_LINES + " lines at once",
        "swallow your kill switch — double-long-press banish lives below every lens",
      ],
      will: [sceneCount + " scene(s), each held at least half a second"],
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

  // -- scene-graph editing (the advanced editor) -----------------------------
  // the triggers a scene can listen for; "timeout" is the timed exit, the rest
  // are physical/gesture events (see figment_stage.lua on_event).
  var TRIGGERS = [
    { key: "timeout", label: "when it ends" },
    { key: "double", label: "double-tap" },
    { key: "single", label: "tap" },
    { key: "long", label: "long-press" },
    { key: "imu:nod", label: "nod" },
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
  function setTransition(scene_, trigger, target) {
    if (trigger === "timeout") { scene_.on_timeout = [{ target: target }]; }
    else { scene_.on = scene_.on || {}; scene_.on[trigger] = { target: target }; }
  }
  function removeTransition(scene_, trigger) {
    if (trigger === "timeout") { delete scene_.on_timeout; }
    else if (scene_.on) { delete scene_.on[trigger]; }
  }
  function listTransitions(scene_) {
    var out = [];
    (scene_.on_timeout || []).forEach(function (t) { out.push({ trigger: "timeout", target: t.target }); });
    if (scene_.on) Object.keys(scene_.on).forEach(function (k) { out.push({ trigger: k, target: scene_.on[k].target }); });
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
    templates: { reps: tReps, focus: tFocus, score: tScore, breathing: tBreathing,
      interval: tInterval, countdown: tCountdown, checklist: tChecklist },
    showcases: SHOWCASES,
  };
});
