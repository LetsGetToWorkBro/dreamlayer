/* search.js — the plugin store's search brain (MARKETPLACE, phase 2.5).
 *
 * One ranked-search engine, shipped with the clients and imported by the
 * Worker — the figment.js pattern. The catalogue lives with the client (the
 * registry can be private), so search runs wherever the catalogue is: the
 * store page and phone app rank their own copy, and the Worker's
 * GET /api/plugins/search ranks the public index for headless callers (the
 * CLI, the Mac panel, third-party tooling).
 *
 * Deliberately NOT a search server. A six-plugin catalogue that may grow to a
 * few thousand doesn't need Typesense and a box to run it on — it needs a good
 * scorer that understands store-speak ("find me a plugin for crypto prices on
 * my HUD" → currency-converter). That's three things:
 *   1. fielded keyword scoring  — a hit in the name outranks a hit in the blurb
 *   2. store-speak stopwords    — "find me a plugin for … on my hud" is noise
 *   3. concept expansion        — "crypto"→currency/money, "calories"→food/nutrition
 * plus typo tolerance (edit distance 1) so "curency" still lands.
 *
 * No DOM, no fetch, no state — pure (catalogue, query) → ranked rows, so it
 * runs in the browser AND under Node/Workers for tests and the API.
 */
(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) module.exports = factory();
  else root.StoreSearch = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // -- what a hit in each field is worth --------------------------------------
  // Name is the strongest signal an author controls; tags are curated; the
  // long detail copy is the weakest (it matches everything eventually).
  var FIELDS = [
    { key: "name",        weight: 6.0 },
    { key: "tags",        weight: 5.0 },
    { key: "description", weight: 2.5 },
    { key: "forwho",      weight: 2.0 },
    { key: "author",      weight: 1.5 },
    { key: "long",        weight: 1.0 },
  ];

  // Store-speak: the words people type around what they actually want.
  // "hud"/"glasses"/"dreamlayer" are here because *everything* in this store
  // is on the HUD — they carry no signal. Stripped only when other tokens
  // remain, so a bare "hud" search still works (see tokenize).
  var STOPWORDS = {};
  ("a an and are can do does find for get give i in is it me my need of on one " +
   "or plugin plugins show shows some something that the this to want when with " +
   "app apps hud glasses dreamlayer").split(" ").forEach(function (w) { STOPWORDS[w] = true; });

  // Concept expansion — the honest core of "semantic" here. Each entry maps a
  // query-side word to catalogue-side vocabulary; expanded terms score at a
  // discount (EXPANDED_FACTOR) so a literal hit always outranks an inferred
  // one. Curated, tiny, and cheap to grow alongside the catalogue: when a new
  // plugin family lands, add its aliases here (a test pins the shape).
  var CONCEPTS = {
    crypto: ["currency", "money", "price", "exchange"],
    bitcoin: ["currency", "money", "price", "exchange"],
    forex: ["currency", "exchange", "rates", "travel"],
    money: ["currency", "price", "shopping"],
    price: ["currency", "shopping", "money"],
    prices: ["currency", "shopping", "money"],
    exchange: ["currency", "rates", "converter"],
    abroad: ["travel", "currency", "foreign"],
    calories: ["food", "nutrition", "nutri"],
    diet: ["food", "nutrition", "allergens"],
    nutrition: ["food", "shopping", "scan"],
    grocery: ["food", "shopping", "shelf"],
    groceries: ["food", "shopping", "shelf"],
    allergy: ["allergens", "food"],
    allergies: ["allergens", "food"],
    music: ["midi", "synth", "drums", "note"],
    instrument: ["midi", "synth", "drums", "music"],
    song: ["music", "midi", "note"],
    jam: ["music", "midi", "band", "mesh"],
    beat: ["drums", "midi", "music"],
    beats: ["drums", "midi", "music"],
    drummer: ["drums", "midi", "music"],
    presentation: ["speaking", "coaching", "filler"],
    presentations: ["speaking", "coaching", "filler"],
    speech: ["speaking", "coaching", "filler", "words"],
    talk: ["speaking", "coaching", "filler"],
    interview: ["speaking", "coaching", "filler"],
    um: ["filler", "speaking", "coaching"],
    emoji: ["reactions", "social", "fun"],
    emojis: ["reactions", "social", "fun"],
    react: ["reactions", "social", "mesh"],
    friends: ["social", "mesh", "circle"],
    party: ["social", "fun", "reactions"],
    scan: ["barcode", "shelf", "food", "shopping"],
    barcode: ["food", "shopping", "scan"],
    translate: ["currency", "converter", "foreign"],
    workout: ["reps", "gym", "fitness", "coaching"],
    gym: ["reps", "fitness", "workout", "coaching"],
    fitness: ["reps", "gym", "workout", "coaching"],
    focus: ["productivity", "coaching", "timer"],
    weather: ["forecast", "sky", "ambient"],
  };
  var EXPANDED_FACTOR = 0.6;

  // How much weaker each match kind is than an exact word hit.
  var PREFIX_FACTOR = 0.7;   // "curren" → "currency"
  var FUZZY_FACTOR = 0.5;    // "curency" → "currency" (one edit)

  // ---------------------------------------------------------------------------

  function words(s) {
    return String(s == null ? "" : s).toLowerCase()
      .replace(/[^a-z0-9]+/g, " ").split(" ").filter(Boolean);
  }

  // Query → tokens. Stopwords are stripped only when something remains without
  // them — so "find me a plugin" degrades to plain matching instead of nothing.
  function tokenize(query) {
    var all = words(query).slice(0, 24);           // bound hostile queries
    var kept = all.filter(function (w) { return !STOPWORDS[w]; });
    return kept.length ? kept : all;
  }

  // One edit (insert / delete / substitute) apart? Only consulted for tokens
  // long enough that a single edit is plausibly a typo, not a different word.
  function oneEdit(a, b) {
    var la = a.length, lb = b.length;
    if (Math.abs(la - lb) > 1) return false;
    var i = 0, j = 0, edits = 0;
    while (i < la && j < lb) {
      if (a[i] === b[j]) { i++; j++; continue; }
      if (++edits > 1) return false;
      if (la > lb) i++;
      else if (lb > la) j++;
      else { i++; j++; }
    }
    return edits + (la - i) + (lb - j) === 1;
  }

  // The per-plugin bag of words, one array per field, built once per rank().
  function docOf(plugin) {
    var doc = { plugin: plugin, fields: [] };
    for (var f = 0; f < FIELDS.length; f++) {
      var v = plugin[FIELDS[f].key];
      doc.fields.push(words(Array.isArray(v) ? v.join(" ") : v));
    }
    return doc;
  }

  // Best single-token score against one document + which word it landed on.
  function tokenHit(token, doc) {
    var best = 0, on = "";
    for (var f = 0; f < FIELDS.length; f++) {
      var weight = FIELDS[f].weight, ws = doc.fields[f];
      for (var i = 0; i < ws.length; i++) {
        var w = ws[i], s = 0;
        if (w === token) s = weight;
        else if (token.length >= 3 && w.indexOf(token) === 0) s = weight * PREFIX_FACTOR;
        else if (token.length >= 5 && oneEdit(token, w)) s = weight * FUZZY_FACTOR;
        if (s > best) { best = s; on = w; }
      }
    }
    return { score: best, word: on };
  }

  /**
   * Rank a catalogue against a query.
   *   rank(plugins, "crypto prices") →
   *     [{plugin, score, matched:["currency","price"]}, …]  best first
   * Zero-score plugins are dropped; ties break on downloads (social proof),
   * then name. Pure function — no I/O, safe everywhere.
   */
  function rank(plugins, query) {
    var tokens = tokenize(query);
    if (!tokens.length || !Array.isArray(plugins) || !plugins.length) return [];
    var docs = plugins.map(docOf);
    var out = [];
    for (var d = 0; d < docs.length; d++) {
      var score = 0, covered = 0, matched = {};
      for (var t = 0; t < tokens.length; t++) {
        var tok = tokens[t];
        var hit = tokenHit(tok, docs[d]);
        // literal miss → try the concept map at a discount
        if (!hit.score && CONCEPTS[tok]) {
          var exp = CONCEPTS[tok];
          for (var e = 0; e < exp.length; e++) {
            var h = tokenHit(exp[e], docs[d]);
            h.score *= EXPANDED_FACTOR;
            if (h.score > hit.score) hit = h;
          }
        }
        if (hit.score > 0) { score += hit.score; covered++; matched[hit.word] = true; }
      }
      if (score <= 0) continue;
      // Reward covering more of the query: a plugin matching both "crypto"
      // and "prices" should beat one matching either twice as hard.
      score *= 0.5 + 0.5 * (covered / tokens.length);
      out.push({ plugin: docs[d].plugin, score: Math.round(score * 1000) / 1000,
                 matched: Object.keys(matched) });
    }
    out.sort(function (a, b) {
      return (b.score - a.score) ||
        ((b.plugin.downloads || 0) - (a.plugin.downloads || 0)) ||
        String(a.plugin.name).localeCompare(String(b.plugin.name));
    });
    return out;
  }

  return { rank: rank, tokenize: tokenize, FIELDS: FIELDS, CONCEPTS: CONCEPTS,
           STOPWORDS: STOPWORDS };
});
