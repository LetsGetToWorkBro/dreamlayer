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

if (fails.length) { console.error("FAIL\n" + fails.join("\n")); process.exit(1); }
console.log("ok — " + K.TEMPLATES.length + " templates valid, graph + listing + events checked, violations caught");
