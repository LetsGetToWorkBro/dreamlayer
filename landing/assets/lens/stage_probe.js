/* stage_probe.js — a thin CLI around LensKit.Stage for cross-checking the JS
 * reference interpreter against the Python one (reality_compiler/v2/interpreter).
 * Reads {fig, script} JSON on stdin; writes a JSON trace on stdout: one frame
 * snapshot after each op. Used by tests/test_lens_builder.py to pin parity so
 * "verified" in Figment Golf means the same thing on both engines.
 *
 *   echo '{"fig":{...},"script":[["step",5],["inject","double"]]}' | node stage_probe.js
 */
"use strict";
var K = require("./figment.js");

function snap(st) {
  var fr = st.frame();
  return {
    scene: st.ended ? "@end" : st.current,
    ended: !!st.ended,
    lines: (fr.lines || []).map(function (l) { return l.text; }),
    remaining: Math.round(st.remaining() * 1000) / 1000,
    pulse: !!fr.pulse_on,
    cadence_phase: fr.cadence_phase || "",
    cadence_level: Math.round((fr.cadence_level || 0) * 1000) / 1000,
    counters: Object.assign({}, st.counters),
  };
}

var chunks = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", function (d) { chunks += d; });
process.stdin.on("end", function () {
  var input = JSON.parse(chunks);
  var st = new K.Stage(input.fig);
  var trace = [snap(st)];                     // initial frame
  (input.script || []).forEach(function (op) {
    if (op[0] === "step") st.step(op[1]);
    else if (op[0] === "inject") st.inject(op[1], op[2]);
    trace.push(snap(st));
  });
  process.stdout.write(JSON.stringify(trace));
});
