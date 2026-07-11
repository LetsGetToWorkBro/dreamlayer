/* juno.js — mounts Juno, the DreamLayer assistant sprite, with TRUE
 * transparency so she sits on any background.
 *
 * She's an ANIMATED WEBP with an alpha channel (her AI-matted idle loop —
 * she drifts, her wings and hair and dress move). A plain <img> plays it on
 * every current browser INCLUDING iOS Safari (14+), which supports animated
 * WebP natively. We deliberately do NOT drive her from a <video> + <canvas>
 * matte anymore: iOS Safari won't decode an off-screen / zero-size video, so
 * that path silently fell back to a still on iPhone. An <img> has no such
 * quirk. Under prefers-reduced-motion we show a still transparent WebP.
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
  // Cache-buster for the sprite assets. Bump this whenever juno_idle*.webp
  // changes — the filenames stay stable, so without it browsers (esp. iOS
  // Safari) keep serving a stale clip. Keep it in sync with the ?v= on the
  // <script src="…/juno.js"> tags so the whole kit refreshes together.
  var V = "?v=3";

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
    ".juno[data-state=\"thinking\"] .juno-media{filter:brightness(1.12) saturate(1.15) drop-shadow(0 0 10px rgba(47,212,196,.35))}" +
    ".juno[data-state=\"success\"] .juno-media{filter:brightness(1.35) saturate(1.2) drop-shadow(0 0 12px rgba(86,211,100,.4))}" +
    "@media (prefers-reduced-motion: reduce){.juno-media{filter:none!important}}";
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
    if (!reduce) el.classList.add("juno-alive");     // hook for per-surface ambience
    el.setAttribute("data-state", opts.state || "idle");
    el.innerHTML = "";

    var img = document.createElement("img");
    img.className = "juno-media";
    img.alt = "Juno, the DreamLayer assistant";
    img.decoding = "async";
    // the animated loop when motion is welcome; the still poster otherwise. If
    // the animation ever fails to load, fall back to the still.
    var still = dir + "juno_idle.webp" + V;
    img.onerror = function () { if (img.src.indexOf("juno_idle.webp") < 0) img.src = still; };
    img.src = reduce ? still : (dir + "juno_idle_anim.webp" + V);
    el.appendChild(img);
    return api(el, img);
  }
  function setState(el, state) { if (el) el.setAttribute("data-state", state || "idle"); }
  function api(el, media) {
    return { el: el, media: media, setState: function (s) { setState(el, s); return this; } };
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
