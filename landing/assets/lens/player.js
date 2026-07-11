/* player.js — a tiny live figment player for a <canvas>. Steps a lens through
 * its scenes and draws it the way the on-glass stage lays it out: rows of text,
 * painted strokes, the final-window pulse, and the breathing cadence halo. Pure
 * DOM + a figment object (no LensKit dependency), so the gallery, the store, or
 * an embed can all render a lens live. UMD → global `LensPlayer`.
 *
 *   var p = new LensPlayer(canvas, figment, {size: 200});
 *   p.start();   // ... p.stop();
 */
(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) module.exports = factory();
  else root.LensPlayer = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var HEX = {
    background: "#000000", surface: "#0E1416", text_primary: "#ECF0F1",
    text_secondary: "#A8B8C0", accent_memory: "#2CC79A", accent_attention: "#E06B52",
    accent_success: "#56D364", accent_error: "#E05252", border_subtle: "#2A3C44",
    status_paused: "#8FA8B2",
  };
  var SZ = { sm: 20, md: 32, lg: 44 }, GPX = { sm: 3, md: 6, lg: 11 };

  function now() { return (typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now(); }
  function mmss(s) { var m = Math.floor(s / 60); return m + ":" + ("0" + (s % 60)).slice(-2); }

  function LensPlayer(canvas, fig, opts) {
    opts = opts || {};
    this.cv = canvas; this.ctx = canvas.getContext("2d");
    this.fig = fig; this.raf = null; this.demoSlot = opts.slot || "";
    this.active = fig ? fig.initial : null; this.t0 = now();
    this.counters = {}; this._resetCounters();
  }
  LensPlayer.prototype._resetCounters = function () {
    this.counters = {};
    var c = this.fig && this.fig.counters;
    if (c) Object.keys(c).forEach((function (n) { this.counters[n] = c[n].start || 0; }).bind(this));
  };
  LensPlayer.prototype._dwell = function (s) { return s.duration_sec != null ? s.duration_sec : 1.8; };
  LensPlayer.prototype._pick = function (s) {
    if (s.duration_sec != null && s.on_timeout && s.on_timeout.length) return s.on_timeout[s.on_timeout.length - 1];
    if (s.on) { var pref = ["imu:nod", "single", "double", "long", "text", "place:enter", "bond:near"];
      for (var i = 0; i < pref.length; i++) if (s.on[pref[i]]) return s.on[pref[i]];
      var k = Object.keys(s.on)[0]; if (k) return s.on[k]; }
    return { target: "@end" };
  };
  LensPlayer.prototype._applyOps = function (t) {
    var self = this;
    (t.counter_ops || []).forEach(function (o) {
      var d = self.fig.counters && self.fig.counters[o.counter]; if (!d) return;
      var v = self.counters[o.counter] || 0, by = o.amount == null ? 1 : o.amount;
      if (o.op === "inc") v += by; else if (o.op === "dec") v -= by; else v = by;
      self.counters[o.counter] = Math.max(d.lo == null ? 0 : d.lo, Math.min(d.hi == null ? 9999 : d.hi, v));
    });
  };
  LensPlayer.prototype._resolve = function (txt, s, el, dur) {
    var self = this;
    return String(txt || "")
      .replace(/\{remaining\}/g, s.duration_sec != null ? mmss(Math.max(0, Math.ceil(dur - el))) : "")
      .replace(/\{remaining_s\}/g, s.duration_sec != null ? String(Math.max(0, Math.ceil(dur - el))) : "")
      .replace(/\{elapsed\}/g, mmss(Math.floor(el)))
      .replace(/\{slot\}/g, self.demoSlot || "…")
      .replace(/\{count:(\w+)\}/g, function (_, n) { return String(self.counters[n] != null ? self.counters[n] : 0); });
  };
  LensPlayer.prototype._tick = function () {
    this.raf = null;
    if (this.fig && this.active) {
      var s = this.fig.scenes[this.active];
      if (s) {
        var el = (now() - this.t0) / 1000, dur = this._dwell(s);
        if (el >= dur) {
          var tr = this._pick(s); this._applyOps(tr);
          var n = tr.target === "@self" ? this.active : tr.target;
          if (n === "@end" || !this.fig.scenes[n]) { n = this.fig.initial; this._resetCounters(); }
          this.active = n; this.t0 = now(); el = 0;
        }
        this._draw(s, el, dur);
      }
    }
    this.raf = requestAnimationFrame(this._tick.bind(this));
  };
  LensPlayer.prototype._draw = function (s, el, dur) {
    var ctx = this.ctx, W = this.cv.width, C = W / 2;
    ctx.clearRect(0, 0, W, W);
    ctx.fillStyle = "#000"; ctx.beginPath(); ctx.arc(C, C, C - 1, 0, 7); ctx.fill();
    ctx.strokeStyle = "rgba(140,190,190,.12)"; ctx.lineWidth = W * 0.008; ctx.beginPath(); ctx.arc(C, C, C * 0.9, 0, 7); ctx.stroke();
    // cadence halo
    if (s.cadence) {
      var per = (s.cadence.in_s || 0) + (s.cadence.hold_s || 0) + (s.cadence.out_s || 0);
      if (per > 0) { var u = el % per, amp;
        if (u < s.cadence.in_s) amp = u / (s.cadence.in_s || 1);
        else if (u < s.cadence.in_s + s.cadence.hold_s) amp = 1;
        else amp = 1 - (u - s.cadence.in_s - s.cadence.hold_s) / (s.cadence.out_s || 1);
        ctx.save(); ctx.globalAlpha = 0.12 + 0.45 * Math.max(0, Math.min(1, amp));
        ctx.strokeStyle = HEX.accent_memory; ctx.lineWidth = W * 0.02;
        ctx.beginPath(); ctx.arc(C, C, C * (0.62 + 0.14 * amp), 0, 7); ctx.stroke(); ctx.restore();
      }
    }
    if (s.duration_sec != null) { var f = Math.max(0, 1 - el / dur);
      ctx.strokeStyle = HEX.accent_memory; ctx.lineWidth = W * 0.025;
      ctx.beginPath(); ctx.arc(C, C, C * 0.94, -Math.PI / 2, -Math.PI / 2 + f * 2 * Math.PI); ctx.stroke();
    }
    var pulseOn = false;
    if (s.pulse && s.duration_sec != null && (dur - el) <= s.pulse.window_sec)
      pulseOn = (Math.floor(el * s.pulse.rate_hz * 2) % 2 === 0);
    var scale = W / 256;
    (s.glyphs || []).forEach(function (g) { var pts = g.points || []; if (pts.length < 2) return;
      ctx.strokeStyle = HEX[g.color] || HEX.accent_attention; ctx.lineWidth = (GPX[g.width] || 6) * scale;
      ctx.lineCap = "round"; ctx.lineJoin = "round"; ctx.beginPath();
      ctx.moveTo(pts[0][0] * W, pts[0][1] * W);
      for (var i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0] * W, pts[i][1] * W);
      ctx.stroke();
    });
    ctx.textAlign = "center"; ctx.textBaseline = "middle";
    var self = this, hasRem = false;
    (s.lines || []).forEach(function (ln) { var y = C - 84 * scale + (ln.row || 0) * 64 * scale;
      if (/\{remaining/.test(ln.content || "")) hasRem = true;
      ctx.fillStyle = pulseOn ? HEX[s.pulse.color] : (HEX[ln.color] || HEX.text_primary);
      ctx.font = ((SZ[ln.size] || 32) * scale) + "px -apple-system,Segoe UI,Roboto,sans-serif";
      ctx.fillText(self._resolve(ln.content, s, el, dur), C, y);
    });
    if (s.duration_sec != null && !hasRem) { var rem = Math.max(0, Math.ceil(dur - el));
      ctx.fillStyle = HEX.text_secondary; ctx.font = (26 * scale) + "px -apple-system,Segoe UI,Roboto";
      ctx.fillText(mmss(rem), C, C + 66 * scale);
    }
  };
  LensPlayer.prototype.start = function () { if (!this.raf) this._tick(); return this; };
  LensPlayer.prototype.stop = function () { if (this.raf) cancelAnimationFrame(this.raf); this.raf = null; return this; };
  LensPlayer.prototype.reset = function () { this.active = this.fig ? this.fig.initial : null; this.t0 = now(); this._resetCounters(); return this; };

  return LensPlayer;
});
