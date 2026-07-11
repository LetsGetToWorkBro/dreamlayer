/* figment.selftest.js — exercises the builder logic under Node (exit 0 = pass).
 * Run by tests/test_lens_builder.py; also handy standalone: `node figment.selftest.js`. */
"use strict";
var K = require("./figment.js");
var fails = [];
function ok(cond, msg) { if (!cond) fails.push(msg); }

// every recipe produces a figment that passes the budget gate
K.TEMPLATES.forEach(function (t) {
  var fig = t.make();
  var r = K.validate(fig);
  ok(r.ok, "template " + t.id + " should be valid: " + JSON.stringify(r.violations));
  var card = K.safetyCard(fig);
  ok(card.ok, "template " + t.id + " safety card ok");
  ok(card.cannot.length >= 4, "safety card lists guarantees");
});

// the interval recipe honours its inputs
var iv = K.templates.interval({ work: 120, rest: 20 });
ok(iv.scenes.work.duration_sec === 120 && iv.scenes.rest.duration_sec === 20, "interval durations applied");

// validation actually catches violations
var bad = K.figment("Bad", "a");
K.addScene(bad, K.scene("a", { duration_sec: 10, on_timeout: [{ target: "nope" }],
                              lines: [K.line("x")] }));
ok(!K.validate(bad).ok, "unknown transition target is rejected");

var pulse = K.figment("Strobe", "a");
K.addScene(pulse, K.scene("a", { duration_sec: 10, on_timeout: [{ target: K.END }],
  lines: [K.line("x")], pulse: { window_sec: 5, rate_hz: 9.0, color: "accent_attention" } }));
ok(!K.validate(pulse).ok, "over-budget pulse (9Hz) is rejected");

var longline = K.figment("Long", "a");
K.addScene(longline, K.scene("a", { duration_sec: 10, on_timeout: [{ target: K.END }],
  lines: [{ content: "x".repeat(40), row: 0, size: "md", color: "text_primary" }] }));
ok(!K.validate(longline).ok, "over-length line is rejected");

// a timed scene with no timeout is caught
var noexit = K.figment("Stuck", "a");
K.addScene(noexit, K.scene("a", { duration_sec: 10, lines: [K.line("x")] }));
ok(!K.validate(noexit).ok, "timed scene with no timeout is rejected");

// scene-graph editing produces valid figments
var g = K.emptyFigment();
ok(K.validate(g).ok, "emptyFigment is valid");
var s1 = K.addBlankScene(g);                       // an event-only scene
K.setTransition(g.scenes.s0, "double", s1.id);     // s0 --double--> s1
K.setTransition(s1, "double", K.END);              // s1 --double--> end
ok(K.validate(g).ok, "graph edits stay valid: " + JSON.stringify(K.validate(g).violations));
var edges = K.graphEdges(g);
ok(edges.some(function (e) { return e.from === "s0" && e.to === s1.id; }), "edge s0->s1 present");
K.deleteScene(g, s1.id);                            // deleting relinks dangling targets
ok(K.graphEdges(g).every(function (e) { return e.to !== s1.id; }), "no dangling edge after delete");
ok(K.validate(g).ok, "still valid after delete");

// a listing carries the figment + a recomputed proof
var L = K.listing(K.templates.countdown(), { author: "Ada", description: "a timer" });
ok(L.kind === "figment-listing" && L.author === "Ada" && L.proof.ok && L.price === 0, "listing packaged");

// an unknown on-event trigger is rejected (parity with the Python grammar)
var evbad = K.figment("Ev", "a");
K.addScene(evbad, K.scene("a", { lines: [K.line("x")], on: { wiggle: { target: K.END } } }));
ok(!K.validate(evbad).ok, "unknown on-event 'wiggle' is rejected");
var evok = K.figment("Ev2", "a");
K.addScene(evok, K.scene("a", { lines: [K.line("x")], on: { "imu:nod": { target: K.END }, double: { target: K.END } } }));
ok(K.validate(evok).ok, "known events (imu:nod, double) are accepted");

// paint layer: a bounded stroke is accepted, an off-display / oversized one is not
var painted = K.figment("Painted", "a");
K.addScene(painted, K.scene("a", { duration_sec: 5, tick: "countdown",
  lines: [K.line("HI", { size: "lg" })], on_timeout: [{ target: K.END }],
  glyphs: [K.glyph([[0.2, 0.2], [0.8, 0.8]], { color: "accent_success", width: "lg" })] }));
ok(K.validate(painted).ok, "a simple painted stroke is accepted: " + JSON.stringify(K.validate(painted).violations));

var offglass = K.figment("Off", "a");
K.addScene(offglass, K.scene("a", { lines: [K.line("x")],
  glyphs: [{ points: [[0.5, 0.5], [1.4, 0.5]], color: "accent_attention", width: "md" }] }));
ok(!K.validate(offglass).ok, "a stroke that leaves the display is rejected");

var toomany = K.figment("Many", "a");
var manyStrokes = [];
for (var gi = 0; gi <= K.BUDGETS.MAX_GLYPHS; gi++) manyStrokes.push(K.glyph([[0.1, 0.1], [0.9, 0.9]]));
K.addScene(toomany, K.scene("a", { lines: [K.line("x")], glyphs: manyStrokes }));
ok(!K.validate(toomany).ok, "more than MAX_GLYPHS strokes is rejected");

// every recipe in the gallery — including the rich ones (counters, gestures,
// painted glyphs, cadence) — is budget-clean
K.TEMPLATES.forEach(function (t) {
  ok(K.validate(t.make()).ok, "recipe '" + t.id + "' is valid: " + JSON.stringify(K.validate(t.make()).violations));
});
// the rep counter really carries a counter + a gesture + a painted stroke
var reps = K.templates.reps();
ok(reps.counters.reps && reps.scenes.count.on["imu:nod"] && reps.scenes.count.glyphs.length,
   "rep counter has a counter, a nod gesture, and a painted tally");

// Ask Juno (client fallback): the creative prompts each map to their rich recipe
[["count my push-ups with a nod", "reps"], ["a focus session that breathes while I work", "focus"],
 ["keep score — tap for us, double-tap for them", "score"], ["box breathing 4 seconds", "breathing"],
 ["interval 3 min work 1 min rest", "interval"]].forEach(function (p) {
  var r = K.composeLocal(p[0]);
  ok(r.matched && r.kind === p[1] && K.validate(r.figment).ok,
     "composeLocal drafts a valid '" + p[1] + "' from: " + p[0] + " (got " + r.kind + ")");
});
ok(!K.composeLocal("xyzzy random gibberish").matched, "composeLocal declines nonsense");

// every tutorial showcase is budget-clean AND exercises a distinct edge
Object.keys(K.showcases).forEach(function (id) {
  ok(K.validate(K.showcases[id]()).ok, "showcase '" + id + "' is valid: " + JSON.stringify(K.validate(K.showcases[id]()).violations));
});
var world = K.showcases.world();
ok(world.scenes.wait.on["place:enter"] && world.scenes.wait.on["bond:near"] && world.scenes.wait.on["ble:3"],
   "the world showcase reacts to place, bond, and BLE triggers");
// the stack showcases: each pulls a real capability
ok(/\{slot\}/.test(K.showcases.whisper().scenes.live.lines[0].content), "whisper streams host text into {slot}");
ok(K.showcases.ask().scenes.idle.on.double.emit === "ask", "ask emits a question for the Brain");
ok(K.showcases.secondSight().scenes.look.on.long.emit === "look", "second sight asks the camera to look");
ok(K.showcases.tethered().scenes.near.on_timeout[0].emit === "beat", "tethered emits a heartbeat back");
ok(K.showcases.threshold().scenes.home.on["place:enter"], "threshold fires on arriving somewhere");
ok(K.showcases.ember().scenes.quiet.on["place:enter"], "ember surfaces a memory where it happened");
ok(K.showcases.coach().counters.reps && K.showcases.coach().scenes.set.on.single.record, "coach logs only clean reps");
var keep = K.showcases.keep();
ok(keep.scenes.count.on["imu:nod"].record === true, "the keep showcase records each nod to the ledger");
var mand = K.showcases.mandala();
ok(mand.scenes.breathe.cadence && mand.scenes.breathe.glyphs.length >= 5, "the mandala breathes and is painted");
var fus = K.showcases.fusion();
ok(fus.scenes.rest.on_timeout.some(function (t) { return t.when && t.when.cmp === "ge"; }),
   "the fusion showcase makes a guarded decision");

if (fails.length) { console.error("FAIL\n" + fails.join("\n")); process.exit(1); }
console.log("ok — " + K.TEMPLATES.length + " templates + " + Object.keys(K.showcases).length +
  " showcases valid, graph + listing + events + paint + askjuno + tour checked, violations caught");
