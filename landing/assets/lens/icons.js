/* icons.js — a tiny inline-SVG icon set for the community pages (gallery, golf).
 * No emoji, no external requests: crisp line icons that inherit `currentColor`
 * and scale with font-size. Two ways to use it:
 *   markup:  <span data-icon="globe"></span>   (auto-filled on DOMContentLoaded)
 *   in JS:   DLIcon("trophy", "ic-gold")        (returns an <svg> string)
 * UMD → global `DLIcon`. */
(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) module.exports = factory();
  else root.DLIcon = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";
  var P = {
    globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3c3 3.2 3 14.8 0 18M12 3c-3 3.2-3 14.8 0 18"/>',
    flag:  '<path d="M7 21V3"/><path d="M7 4h10l-2.6 3L17 10H7"/>',
    spark: '<path d="M12 4l1.7 5.3L19 11l-5.3 1.7L12 18l-1.7-5.3L5 11l5.3-1.7z"/>',
    shield:'<path d="M12 3l7 3v5c0 4.5-3 7.6-7 9-4-1.4-7-4.5-7-9V6z"/><path d="M9 12l2 2 4-4"/>',
    link:  '<path d="M9 15l6-6"/><path d="M11 6.5l1-1a4 4 0 016 6l-1 1"/><path d="M13 17.5l-1 1a4 4 0 01-6-6l1-1"/>',
    send:  '<path d="M21 3L3 11l7 2.8L13 21z"/><path d="M21 3L10 13.8"/>',
    tent:  '<path d="M4 20L12 4l8 16"/><path d="M4 20h16"/><path d="M12 4v16"/><path d="M8.4 11.5L12 20M15.6 11.5L12 20"/>',
    trophy:'<path d="M8 4h8v4.5a4 4 0 01-8 0z"/><path d="M8 6H5.5a2 2 0 002.3 3M16 6h2.5a2 2 0 01-2.3 3"/><path d="M12 12.5V16M9 20h6l-1-4h-4z"/>',
    medal: '<path d="M9 3l2.2 5M15 3l-2.2 5"/><circle cx="12" cy="15" r="5.6"/><path d="M12 12.4l.85 1.7 1.9.28-1.37 1.34.32 1.88L12 16.8l-1.7.9.32-1.88-1.37-1.34 1.9-.28z" fill="currentColor" stroke="none"/>',
    timer: '<path d="M10 2.5h4"/><path d="M12 5v2.5"/><circle cx="12" cy="14" r="8"/><path d="M12 14v-3.5"/>',
    pulse: '<path d="M2 12h4.5L9 6l4 12 2.5-6H22"/>',
    score: '<rect x="4" y="5" width="16" height="14" rx="2"/><path d="M12 5v14M8 10v4M16 10v4"/>',
    nod:   '<path d="M12 20V6"/><path d="M6 12l6-6 6 6"/>',
    home:  '<path d="M4 11l8-7 8 7"/><path d="M6 10v9h12v-9"/>',
  };
  function svg(name, cls) {
    var body = P[name];
    if (!body) return "";
    return '<svg class="ic' + (cls ? " " + cls : "") + '" viewBox="0 0 24 24" fill="none" ' +
      'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" ' +
      'aria-hidden="true" focusable="false">' + body + "</svg>";
  }
  svg.fill = function (rootEl) {
    var nodes = (rootEl || (typeof document !== "undefined" ? document : null));
    if (!nodes) return;
    [].forEach.call(nodes.querySelectorAll("[data-icon]"), function (el) {
      if (el.__iconed) return;
      el.innerHTML = svg(el.getAttribute("data-icon"), el.getAttribute("data-icon-cls"));
      el.__iconed = true;
    });
  };
  if (typeof document !== "undefined")
    document.addEventListener("DOMContentLoaded", function () { svg.fill(); });
  return svg;
});
