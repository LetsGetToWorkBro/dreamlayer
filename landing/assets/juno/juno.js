/* juno.js — mounts Juno, the DreamLayer assistant sprite, with TRUE
 * transparency so she sits on any background.
 *
 * She's rendered on black; the source is a single H.264 clip that packs the
 * COLOR frame on top and a LUMA ALPHA MATTE on the bottom. We play it muted,
 * off-screen, and composite the two halves onto a <canvas> every frame — the
 * matte's brightness becomes the pixel's alpha. This animates on every browser
 * incl. iOS Safari (which supports neither VP9-alpha nor HEVC-alpha over the
 * open web). Under prefers-reduced-motion (or before play) we show a still
 * transparent WebP.
 *
 *   <div data-juno></div>                         auto-mounts on DOMContentLoaded
 *   var j = Juno.mount(el);  j.setState("thinking");   // idle|thinking|success
 *
 * UMD → global `Juno`. */
(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) module.exports = factory();
  else root.Juno = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  var reduce = (typeof matchMedia !== "undefined") &&
    matchMedia("(prefers-reduced-motion: reduce)").matches;
  var RENDER_W = 384;   // cap the canvas' internal width — bounds the per-frame cost

  function base() {
    try {
      var s = document.currentScript || (function () {
        var all = document.getElementsByTagName("script");
        for (var i = all.length - 1; i >= 0; i--) if (/juno\.js(\?|$)/.test(all[i].src)) return all[i];
        return null;
      })();
      if (s && s.src) return s.src.replace(/juno\.js(\?.*)?$/, "");
    } catch (e) {}
    return "./assets/juno/";
  }
  var B = base();

  var STYLE = ".juno{position:relative;display:block;pointer-events:none;line-height:0}" +
    ".juno-media{width:100%;height:auto;object-fit:contain;display:block;transition:filter .5s ease}" +
    ".juno-src{position:absolute;width:2px;height:2px;opacity:0;pointer-events:none;left:-9999px;top:0}" +
    ".juno[data-state=\"thinking\"] .juno-media{filter:brightness(1.12) saturate(1.15) drop-shadow(0 0 10px rgba(47,212,196,.35))}" +
    ".juno[data-state=\"success\"] .juno-media{filter:brightness(1.35) saturate(1.2) drop-shadow(0 0 12px rgba(86,211,100,.4))}" +
    // she breathes even on the still poster — transform only, so it never fights
    // the state filters above. Richer per-surface motion can override this.
    "@keyframes junoBreathe{0%,100%{transform:translateZ(0) scale(1)}50%{transform:translateZ(0) scale(1.015)}}" +
    ".juno-alive .juno-media{animation:junoBreathe 6.5s ease-in-out infinite;will-change:transform}" +
    "@media (prefers-reduced-motion: reduce){.juno-media{filter:none!important}.juno-alive .juno-media{animation:none!important}}";
  function injectStyle() {
    if (document.getElementById("juno-style")) return;
    var st = document.createElement("style"); st.id = "juno-style"; st.textContent = STYLE;
    (document.head || document.documentElement).appendChild(st);
  }

  function mount(el, opts) {
    opts = opts || {};
    var dir = opts.base || B;
    injectStyle();
    el.classList.add("juno");
    if (!reduce) el.classList.add("juno-alive");     // gentle breathing everywhere
    el.setAttribute("data-state", opts.state || "idle");
    el.innerHTML = "";

    var poster = document.createElement("img");
    poster.className = "juno-media"; poster.src = dir + "juno_idle.webp";
    poster.alt = "Juno, the DreamLayer assistant";
    el.appendChild(poster);
    if (reduce) return api(el, null);                 // stillness for reduced-motion

    var canvas = document.createElement("canvas");
    canvas.className = "juno-media"; canvas.setAttribute("aria-hidden", "true");
    canvas.style.display = "none";                    // shown once the first frame is drawn
    el.appendChild(canvas);

    var video = document.createElement("video");
    video.className = "juno-src";
    video.muted = true; video.defaultMuted = true; video.loop = true; video.autoplay = true;
    video.playsInline = true; video.setAttribute("playsinline", ""); video.setAttribute("webkit-playsinline", "");
    video.preload = "auto"; video.setAttribute("aria-hidden", "true");
    // mp4 (H.264) first — universal on real browsers incl. iOS; webm (VP9) is
    // the fallback for engines without H.264. Both pack colour-over-matte.
    video.innerHTML = '<source src="' + dir + 'juno_idle_packed.mp4" type="video/mp4">' +
                      '<source src="' + dir + 'juno_idle_packed.webm" type="video/webm">';
    el.appendChild(video);

    var ctx = canvas.getContext("2d");
    var off = document.createElement("canvas"), octx = off.getContext("2d", { willReadFrequently: true });
    var vis = true, raf = null, sized = false, firstDrawn = false;

    function size() {
      var vw = video.videoWidth, vh = (video.videoHeight / 2) | 0;   // top color, bottom matte
      if (!vw || !vh) return false;
      var rw = Math.min(vw, RENDER_W), rh = Math.round(rw * vh / vw);
      canvas.width = off.width = rw; canvas.height = off.height = rh;
      sized = true; return true;
    }
    var giveUp = false;
    function draw() {
      raf = null;
      if (!giveUp && video.readyState >= 2 && (sized || size())) {
        var w = canvas.width, h = canvas.height;
        try {
          octx.drawImage(video, 0, 0, video.videoWidth, video.videoHeight / 2, 0, 0, w, h);
          var col = octx.getImageData(0, 0, w, h);
          octx.drawImage(video, 0, video.videoHeight / 2, video.videoWidth, video.videoHeight / 2, 0, 0, w, h);
          var mat = octx.getImageData(0, 0, w, h), cd = col.data, md = mat.data;
          for (var i = 0; i < cd.length; i += 4) cd[i + 3] = md[i];   // alpha = matte luma
          ctx.putImageData(col, 0, 0);
          if (!firstDrawn) { firstDrawn = true; canvas.style.display = ""; poster.style.display = "none"; }
        } catch (e) {
          // e.g. a tainted canvas (cross-origin video) — keep the still poster
          giveUp = true; canvas.style.display = "none"; poster.style.display = ""; stop(); return;
        }
      }
      if (vis) raf = requestAnimationFrame(draw);
    }
    function start() { var p = video.play(); if (p && p.catch) p.catch(function () {}); if (!raf && vis) draw(); }
    function stop() { video.pause(); if (raf) cancelAnimationFrame(raf); raf = null; }

    video.addEventListener("loadeddata", start);
    if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (es) {
        es.forEach(function (e) { vis = e.isIntersecting; if (vis) start(); else stop(); });
      }, { rootMargin: "160px" }).observe(el);
    } else { start(); }
    return api(el, video);
  }
  function setState(el, state) { if (el) el.setAttribute("data-state", state || "idle"); }
  function api(el, v) {
    return { el: el, video: v, setState: function (s) { setState(el, s); return this; } };
  }
  if (typeof document !== "undefined") {
    document.addEventListener("DOMContentLoaded", function () {
      [].forEach.call(document.querySelectorAll("[data-juno]"), function (el) {
        if (!el.__juno) el.__juno = mount(el, { state: el.getAttribute("data-juno-state") || "idle" });
      });
    });
  }
  return { mount: mount, setState: setState };
});
