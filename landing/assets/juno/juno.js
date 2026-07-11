/* juno.js — mounts Juno, the DreamLayer assistant sprite, as a screen-blended
 * looping video. She's rendered on pure black, so `mix-blend-mode: screen`
 * drops her light onto the dark UI with no alpha channel (the same trick the
 * gallery HUD uses). Self-contained: injects its own CSS, lazy-plays only when
 * on screen, and falls back to a still poster under prefers-reduced-motion.
 *
 *   <div data-juno></div>                       auto-mounts on DOMContentLoaded
 *   var j = Juno.mount(el);  j.setState("thinking");   // idle|thinking|success
 *
 * States reuse the one idle loop today (a light/º filter shift); when more
 * clips exist they slot in by swapping sources — the API doesn't change.
 * UMD → global `Juno`. */
(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) module.exports = factory();
  else root.Juno = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  var reduce = (typeof matchMedia !== "undefined") &&
    matchMedia("(prefers-reduced-motion: reduce)").matches;

  function base() {
    // resolve the folder this script was loaded from, so pages can include it
    // from anywhere without hard-coding the asset path
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
    ".juno-media{width:100%;height:100%;object-fit:contain;display:block;" +
      "mix-blend-mode:screen;transition:filter .5s ease}" +
    ".juno[data-state=\"thinking\"] .juno-media{filter:brightness(1.12) saturate(1.15);" +
      "animation:junoBreathe 2.4s ease-in-out infinite}" +
    ".juno[data-state=\"success\"] .juno-media{filter:brightness(1.4) saturate(1.25)}" +
    "@keyframes junoBreathe{0%,100%{opacity:.92}50%{opacity:1}}" +
    "@media (prefers-reduced-motion: reduce){.juno-media{animation:none!important;filter:none!important}}";
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
    el.setAttribute("data-state", opts.state || "idle");
    el.innerHTML = "";
    if (reduce) {                                    // stillness for reduced-motion
      var img = document.createElement("img");
      img.className = "juno-media"; img.src = dir + "juno_idle_poster.webp";
      img.alt = "Juno, the DreamLayer assistant"; el.appendChild(img);
      return api(el, null);
    }
    var v = document.createElement("video");
    v.className = "juno-media";
    v.muted = true; v.defaultMuted = true; v.loop = true; v.autoplay = true;
    v.playsInline = true; v.setAttribute("playsinline", ""); v.setAttribute("webkit-playsinline", "");
    v.preload = "metadata"; v.poster = dir + "juno_idle_poster.webp";
    v.setAttribute("aria-label", "Juno, the DreamLayer assistant");
    v.innerHTML = '<source src="' + dir + 'juno_idle.webm" type="video/webm">' +
                  '<source src="' + dir + 'juno_idle.mp4" type="video/mp4">';
    el.appendChild(v);
    var play = function () { var p = v.play(); if (p && p.catch) p.catch(function () {}); };
    if ("IntersectionObserver" in window) {
      var io = new IntersectionObserver(function (es) {
        es.forEach(function (e) { if (e.isIntersecting) play(); else v.pause(); });
      }, { rootMargin: "120px" });
      io.observe(el);
    } else { play(); }
    return api(el, v);
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
