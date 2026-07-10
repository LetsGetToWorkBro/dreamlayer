/* ============================================================================
   halo-sim.js — the Halo, running in your browser.

   A faithful client-side port of the DreamLayer stack the Python simulator
   runs (host-python/src/dreamlayer): the "Hey Juno" voice grammar
   (orchestrator/voice.py), the orchestrator loop, Social Lens recall, Waypath,
   the native timer/interval/clock Figments (reality_compiler/v2), and the HUD
   card renderer (hud/renderer.py + themes.py). Same behaviours, same palette,
   drawn on a <canvas> instead of a 256px round display.

   No build step, no dependency. window.Halo = { Sim, Glass, palette }.
   ========================================================================== */
(function (root) {
  "use strict";

  /* ---- palette: hud/themes.py, the only colours the glass draws ---------- */
  var C = {
    bg: "#000000",
    text: "#ECF0F1",       // TEXT_PRIMARY
    text2: "#A8B8C0",      // TEXT_SECONDARY
    ghost: "#58686F",      // TEXT_GHOST
    teal: "#2CC79A",       // ACCENT_MEMORY
    tealDim: "#1A7A60",
    coral: "#E06B52",      // ACCENT_ATTENTION / debts
    green: "#56D364",      // ACCENT_SUCCESS
    amber: "#FF6600",      // WARNING_AMBER (fact-check "check this")
    recall: "#5B7CFF",     // face-recall eyebrow
    border: "#2A3C44",
  };

  /* ======================================================================
     1. VOICE GRAMMAR — port of orchestrator/voice.py parse_intent
     ====================================================================== */
  var WAKE = ["hey juno", "ok juno", "okay juno", "juno",
    "hey dreamlayer", "ok dreamlayer", "dreamlayer"];

  function stripWake(text) {
    var t = (text || "").trim(), low = t.toLowerCase();
    for (var i = 0; i < WAKE.length; i++) {
      var w = WAKE[i];
      if (low === w || low.indexOf(w + " ") === 0 || low.indexOf(w + ",") === 0) {
        return t.slice(w.length).replace(/^[\s,.!—-]+/, "").trim();
      }
    }
    return t;
  }

  var WORDNUM = { a: 1, an: 1, one: 1, two: 2, three: 3, four: 4, five: 5, six: 6,
    seven: 7, eight: 8, nine: 9, ten: 10, eleven: 11, twelve: 12, fifteen: 15,
    twenty: 20, thirty: 30, forty: 40, "forty-five": 45, fifty: 50, sixty: 60, ninety: 90 };
  var UNIT = { hour: 3600, hours: 3600, hr: 3600, hrs: 3600, minute: 60, minutes: 60,
    min: 60, mins: 60, second: 1, seconds: 1, sec: 1, secs: 1 };
  function num(tok) { return WORDNUM[tok] != null ? WORDNUM[tok] : parseFloat(tok); }

  var DUR_RE = /(\d+(?:\.\d+)?|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|forty-five|forty|fifty|sixty|ninety)\s*(hours?|hrs?|minutes?|mins?|seconds?|secs?)\b/g;
  var ROUNDS_RE = /(\d+|one|two|three|four|five|six|seven|eight|nine|ten|twelve)\s*(rounds?|sets?|reps?|times|intervals?|cycles?)\b/;

  function durations(t) {
    var out = [], m; DUR_RE.lastIndex = 0;
    while ((m = DUR_RE.exec(t))) {
      var u = m[2].replace(/s$/, ""); out.push(num(m[1]) * (UNIT[u] != null ? UNIT[u] : UNIT[m[2]]));
    }
    return out;
  }

  function parseTimerClock(t) {
    var hasTimer = /\btimer\b|\binterval/.test(t);
    if (/\b(cancel|stop|clear|dismiss|kill)\b.*\b(timer|intervals?|clock|countdown)\b/.test(t) ||
        /\b(timer|clock|countdown)s?\s+(off|stop)\b/.test(t))
      return { kind: "timer_cancel", args: {} };
    if (!hasTimer) {
      if (/\bwhat(?:'?s| is)?\s+the\s+time\b/.test(t) || t.indexOf("what time is it") >= 0 ||
          /\btell me the time\b/.test(t)) return { kind: "clock", args: { mode: "time" } };
      if (/\b(show|put|display|start)\b.*\bclock\b/.test(t) ||
          /\bclock\b.*\b(on|up|hud|please)\b/.test(t) || t === "clock" || t === "a clock")
        return { kind: "clock", args: { mode: "show" } };
    }
    var d = durations(t);
    var isInterval = t.indexOf("interval") >= 0 ||
      (d.length >= 2 && /\b(on|off|work|working|rest|active|recover)\b/.test(t));
    if (isInterval && d.length) {
      var rm = ROUNDS_RE.exec(t);
      return { kind: "interval", args: { work: d[0], rest: d.length >= 2 ? d[1] : d[0],
        rounds: rm ? num(rm[1]) : null } };
    }
    var wants = hasTimer || /\bcount ?down\b/.test(t) || /\bset (?:a |an )?(?:timer|alarm)\b/.test(t);
    if (wants && d.length) return { kind: "timer", args: { seconds: d.reduce(function (a, b) { return a + b; }, 0) } };
    return null;
  }

  /* -- debts: "Marcus owes me $20" / "I owe Dana lunch" -- */
  var PRONOUNS = { he: 1, she: 1, they: 1, him: 1, her: 1, them: 1 };
  function cleanAmt(s) { return (s || "").replace(/\s+/g, " ").replace(/^[\s.,!?]+|[\s.,!?]+$/g, ""); }
  function parseDebt(r) {
    var core = r.trim(), m = core.match(/^(?:remember|note)(?:\s+that)?\s+(.+)$/i);
    if (m) core = m[1].trim();
    var ms = core.match(/^(?:i\s+)?(?:paid\s+(?:back\s+)?|settled\s+up\s+with\s+|squared\s+up\s+with\s+|clear\s+with\s+)(\w[\w'’.-]*)/i) ||
      core.match(/^(\w[\w'’.-]*)\s+(?:paid|got)\s+me\s+back\b/i);
    if (ms) return { kind: "debt_settle", args: { who: ms[1] } };
    var mi = core.match(/^i\s+owe\s+(\w[\w'’.-]*)\s+(.+)$/i);
    if (mi) return { kind: "debt", args: { who: mi[1], dir: "i_owe", what: cleanAmt(mi[2]) } };
    var mt = core.match(/^(.+?)\s+owes?\s+(?:me|you)\s+(.+)$/i);
    if (mt) {
      var who = mt[1].trim();
      return { kind: "debt", args: { who: PRONOUNS[who.toLowerCase()] ? null : who,
        dir: "they_owe", what: cleanAmt(mt[2]) } };
    }
    return null;
  }

  /* -- introductions: "this is my colleague Sarah, she runs marketing" -- */
  var SOFT = ["i'?m", "i am", "this is", "that'?s", "meet", "have you met",
    "introduce you to", "say hi to", "say hello to"];
  var DET = /^(my|our|the|a|an)\s+/i, TITLES = /^(dr|prof|mr|mrs|ms|sir)\.?$/i;
  function parseIntroEx(u) {
    u = (u || "").trim();
    for (var i = 0; i < SOFT.length; i++) {
      var re = new RegExp("^(?:" + SOFT[i] + ")\\s+(.+)$", "i"), m = u.match(re);
      if (!m) continue;
      var rest = m[1].trim().split(/\s+/), rel = [], j = 0;
      if (rest[0] && DET.test(rest[0] + " ")) { j = 1; }
      // up to ~5 lowercase relation words before the capitalised name
      var relWords = [];
      while (j < rest.length && relWords.length < 5) {
        var w = rest[j];
        if (TITLES.test(w)) { j++; continue; }
        if (/^[A-Z]/.test(w)) break;                 // the name
        if (!/^[a-z][a-z'-]*$/.test(w)) break;
        relWords.push(w); j++;
      }
      if (j >= rest.length) return null;
      var name = rest[j].replace(/[^A-Za-z'’-].*$/, "");
      if (!/^[A-Z]/.test(name)) return null;
      rel = relWords.join(" ");
      return { name: name.replace(/['’]s$/, ""), relation: rel || null, idx: j };
    }
    return null;
  }
  function parseMeet(r) {
    var core = r.trim(), m = core.match(/^(?:remember|note|jot down|make a note)(?:\s+that)?\s+(.+)$/i);
    if (m) core = m[1].trim();
    var p = parseIntroEx(core);
    if (!p) return null;
    var note = null, idx = core.toLowerCase().indexOf(p.name.toLowerCase());
    if (idx >= 0) {
      var tail = core.slice(idx + p.name.length).replace(/^[\s,;:.\-–—]+/, "")
        .replace(/^(?:and|who)\s+/i, "").trim();
      note = tail || null;
    }
    return { kind: "meet_person", args: { who: p.name, relation: p.relation, note: note } };
  }

  /* -- notes about a person: "remember Maya's into climbing" -- */
  var REMEMBER = /^(?:remember|note|jot down|make a note)(?:\s+that)?\s+(.+)$/i;
  var WEARER = /^(?:i|i'?m|im|my|me|myself)\b/i;
  var PRONOUN_LEAD = /^(he|she|they|him|her|them|this\s+(?:person|guy|woman|man|lady|dude))\b(.*)$/i;
  var NAME_LEAD = /^([A-Z][a-zA-Z.'-]*)(?:['’]s)?\s+(.+)$/;
  var NOTNAME = { the: 1, to: 1, that: 1, this: 1, it: 1, when: 1, where: 1, how: 1, what: 1, there: 1, here: 1, and: 1, but: 1 };
  function stripCopula(f) { return f.replace(/^(?:is|are|was|were|'?s)\s+/i, "").trim(); }
  function parseNote(r) {
    var m = REMEMBER.exec(r.trim()); if (!m) return null;
    var rest = m[1].trim();
    if (WEARER.test(rest)) return null;
    var pm = PRONOUN_LEAD.exec(rest);
    if (pm) { var f = stripCopula(pm[2].trim()); return f ? { kind: "note_person", args: { who: null, note: f } } : null; }
    var nm = NAME_LEAD.exec(rest);
    if (nm && !NOTNAME[nm[1].toLowerCase()]) {
      var fact = stripCopula(nm[2].trim());
      if (fact) return { kind: "note_person", args: { who: nm[1], note: fact } };
    }
    return null;
  }

  /* -- stash: "I left my bike at the north rack" (with the blocklist) -- */
  var LOC = "(?:at|in|on|by|near|under|underneath|inside|behind|next\\s+to|beside)";
  var NOT_THING = ("mom mother dad father parent parents brother brothers sister sisters wife " +
    "husband partner boyfriend girlfriend son daughter kid kids child children family friend " +
    "friends buddy boss coworker colleague roommate aunt uncle cousin grandma grandmother grandpa " +
    "grandfather nephew niece baby sitter nanny doctor dentist therapist team guy guys everyone " +
    "everybody job work career shift meeting appointment interview call class lecture exam test " +
    "flight train bus ride birthday anniversary wedding party dinner lunch breakfast reservation " +
    "game match show concert faith heart mind trust hope luck life word words promise message " +
    "voicemail ball eye eyes head back foot feet hand hands alarm timer clock countdown reminder " +
    "alert early late everything nothing").split(" ").reduce(function (o, w) { o[w] = 1; return o; }, {});
  var NOT_PLACE = /^(?:\d{1,2}(?::\d{2})?\s*(?:am|pm|o'?clock)?|noon|midnight|dawn|dusk|monday|tuesday|wednesday|thursday|friday|saturday|sunday|today|tonight|tomorrow|yesterday|silent|mute|vibrate|hold|do\s+not\s+disturb|you|me|him|her|them|us|it|that)[.!]?$/i;
  var STASH_LEFT = new RegExp("^(?:i\\s+)?(?:left|put|stashed?|dropped|stowed|set)\\s+(?:my\\s+|the\\s+|our\\s+|a\\s+|an\\s+)?(.+?)\\s+" + LOC + "\\s+(.+)$", "i");
  var STASH_ADV = /^(?:i\s+)?(?:left|put|stashed?|dropped|stowed|set)\s+(?:my\s+|the\s+|our\s+)?(.+?)\s+(downstairs|upstairs|outside|inside|out\s+front|out\s+back)$/i;
  var STASH_PARK = new RegExp("^(?:i|i'?m|i\\s+am|we|we'?re|we\\s+are)\\s+parked\\s+(?:the\\s+car\\s+)?" + LOC + "\\s+(.+)$", "i");
  var STASH_IS = new RegExp("^(?:my|our)\\s+(.+?)(?:['’]s|\\s+(?:is|are))\\s+" + LOC + "\\s+(.+)$", "i");
  function cleanSubj(s) { return (s || "").trim().replace(/^(?:my|the|our|a|an)\s+/i, "").trim(); }
  function stashable(subj, place) {
    if (!subj || !place) return false;
    var toks = subj.split(/\s+/).map(function (t) { return t.replace(/['’.,!?]/g, "").toLowerCase(); });
    for (var i = 0; i < toks.length; i++) if (NOT_THING[toks[i]]) return false;
    return !NOT_PLACE.test(place.trim());
  }
  function parseStash(r) {
    var core = r.trim(), m = core.match(/^(?:remember|note)(?:\s+that)?\s+(.+)$/i);
    if (m) core = m[1].trim();
    var rx = [STASH_LEFT, STASH_IS, STASH_ADV], mm;
    for (var i = 0; i < rx.length; i++) {
      mm = rx[i].exec(core);
      if (mm) { var s = cleanSubj(mm[1]), p = mm[2].trim(); if (stashable(s, p)) return { kind: "stash", args: { subject: s, place: p } }; }
    }
    mm = STASH_PARK.exec(core);
    if (mm && stashable("car", mm[1].trim())) return { kind: "stash", args: { subject: "the car", place: mm[1].trim() } };
    return null;
  }

  function parseIntent(text) {
    var raw = stripWake(text), r = raw.replace(/[?.!]+$/, ""), t = r.toLowerCase().trim();
    if (!t) return { kind: "ask", args: { query: "" } };

    var m = r.match(/^(?:reply|respond|text|message)\s+(?:to\s+)?(\w[\w'.-]*)(?:[,:]?\s+(?:with|saying|that)\s+(.*))?$/i);
    if (m) return { kind: "reply", args: { to: m[1], text: (m[2] || "").trim() } };

    m = r.match(/^(?:where'?s|where is|where are|where did i (?:leave|put|park))\s+(?:my\s+|the\s+)?(.+)$/i);
    if (m) return { kind: "locate", args: { subject: m[1].trim() } };
    if (/^where (?:did i park|do i park|am i parked)$/.test(t)) return { kind: "locate", args: { subject: "car" } };

    if (/^what (?:did|does|is|are)\s+\w+.*(need|want|say|said|owe|owes)/.test(t))
      return { kind: "recall", args: { query: raw.trim() } };
    if (t.indexOf("what did i miss") >= 0 || t.indexOf("anything new") >= 0 || t.indexOf("what's new") >= 0)
      return { kind: "missed", args: {} };
    if (t.indexOf("brief") >= 0 || t === "my day" || t === "what's my day" || t === "whats my day")
      return { kind: "brief", args: {} };
    var fc = r.match(/^(?:is it true(?: that)?|is that (?:true|real|correct)|fact.?check|verify|check (?:that|this))\b\s*(.*)$/i);
    if (fc) return { kind: "fact_check", args: { claim: (fc[1] || raw).trim() } };

    var d = parseDebt(r); if (d) return d;
    var mt = parseMeet(r); if (mt) return mt;
    var nt = parseNote(r); if (nt) return nt;
    var tc = parseTimerClock(t); if (tc) return tc;
    var st = parseStash(r); if (st) return st;
    return { kind: "ask", args: { query: raw.trim() } };
  }

  /* -- learn: "call me Sam" / "remember I prefer aisle seats" -- */
  function parseLearn(text) {
    var t = stripWake(text).trim();
    var m = t.match(/^(?:call me|i'?m|i am|my name is|name'?s)\s+([A-Z][\w'-]*)\b/i);
    if (m && /^[A-Z]/.test(m[1])) return { kind: "name", value: m[1] };
    m = t.match(/^remember(?:\s+that)?\s+i\s+(?:prefer|like|always|usually|hate|don'?t|do not|need|want)\b(.*)$/i);
    if (m) return { kind: "pref", value: ("I " + t.replace(/^remember(?:\s+that)?\s+/i, "").replace(/^i\s+/i, "")).trim() };
    return null;
  }

  /* ======================================================================
     2. FIGMENT STAGE — timer / interval / clock, ticked in real time
     (native.py builders + interpreter.py Stage, distilled)
     ====================================================================== */
  function fmtClock(secs) {
    secs = Math.max(0, Math.ceil(secs));
    return secs >= 60 ? (Math.floor(secs / 60) + ":" + String(secs % 60).padStart(2, "0")) : String(secs);
  }
  function spoken(secs) {
    secs = Math.round(secs);
    if (secs % 3600 === 0 && secs >= 3600) { var h = secs / 3600; return h + (h === 1 ? " hour" : " hours"); }
    if (secs % 60 === 0 && secs >= 60) { var mm = secs / 60; return mm + (mm === 1 ? " minute" : " minutes"); }
    if (secs < 60) return secs + (secs === 1 ? " second" : " seconds");
    var m = Math.floor(secs / 60), s = secs % 60;
    return m + " min " + s + " sec";
  }

  function Figment(kind, args) {
    this.kind = kind; this.id = "fig_" + Math.floor(now() * 1000).toString(36);
    this.ended = false; this.clock = 0; this.label = (args && args.label) || "";
    if (kind === "timer") { this.total = args.seconds; this.remaining = args.seconds; }
    else if (kind === "interval") {
      this.work = args.work; this.rest = args.rest; this.rounds = args.rounds || null;
      this.phase = "work"; this.round = 1; this.remaining = args.work;
    } else if (kind === "clock") { /* live time */ }
  }
  Figment.prototype.step = function (dt) {
    if (this.ended || this.kind === "clock") return;
    this.clock += dt; this.remaining -= dt;
    if (this.remaining > 0) return;
    if (this.kind === "timer") { this.remaining = 0; this.done = true; this.ended = false; this._doneAt = this._doneAt || this.clock; if (this.clock - this._doneAt > 30) this.ended = true; return; }
    // interval: advance phase
    if (this.phase === "work") { this.phase = "rest"; this.remaining = this.rest; }
    else {
      this.round += 1;
      if (this.rounds && this.round > this.rounds) { this.ended = true; return; }
      this.phase = "work"; this.remaining = this.work;
    }
  };
  Figment.prototype.frame = function () {
    if (this.ended) return { ended: true };
    if (this.kind === "clock") {
      var d = new Date(), hh = d.getHours() % 12 || 12, mm = String(d.getMinutes()).padStart(2, "0");
      var ap = d.getHours() < 12 ? "AM" : "PM";
      return { lines: [{ t: "CLOCK", c: C.ghost, s: "sm", row: 0 }, { t: hh + ":" + mm, c: C.text, s: "hero", row: 2 }, { t: ap, c: C.text2, s: "sm", row: 3 }] };
    }
    if (this.kind === "timer") {
      if (this.done) return { lines: [{ t: this.label || "TIMER", c: C.ghost, s: "sm", row: 0 }, { t: "DONE", c: C.coral, s: "hero", row: 2 }, { t: "hold to dismiss", c: C.ghost, s: "xs", row: 4 }], pulseOn: pulseAt(this.clock, 2), pulseColor: C.coral };
      var pulse = this.remaining <= 10;
      return { lines: [{ t: (this.label || "TIMER").toUpperCase(), c: C.ghost, s: "sm", row: 0 }, { t: fmtClock(this.remaining), c: pulse ? C.coral : C.text, s: "hero", row: 2 }], pulseOn: pulse && pulseAt(this.clock, 2), pulseColor: C.coral };
    }
    // interval
    var isWork = this.phase === "work", pw = this.remaining <= 3;
    var head = isWork ? "WORK" : "REST";
    var sub = this.rounds ? ("round " + this.round + " / " + this.rounds) : ("round " + this.round);
    return { lines: [{ t: head, c: isWork ? C.teal : C.text2, s: "sm", row: 0 }, { t: fmtClock(this.remaining), c: pw ? C.coral : C.text, s: "hero", row: 2 }, { t: sub, c: C.ghost, s: "xs", row: 4 }], pulseOn: pw && pulseAt(this.clock, 2), pulseColor: C.coral };
  };
  function pulseAt(clk, hz) { return (Math.floor(clk * hz * 2) % 2) === 0; }

  /* ======================================================================
     3. THE ORCHESTRATOR — handleVoice / lookAt / gesture / veil
     ====================================================================== */
  var FACES = { "face-a": 0.82, "face-b": 0.37, "face-c": 0.61 };

  /* ---- Juno answer engine — honest in-browser computation + a small demo
     set. Real math / unit / tip / temperature answers; a curated fact & phrase
     set for the demo. Anything else returns null so Juno answers honestly that
     it would reach your Brain. On the glasses the Brain answers on the glass;
     here we answer what a browser honestly can, and show it on the same card. -- */
  var UNITS = {
    mi:["km",1.60934], mile:["km",1.60934], miles:["km",1.60934],
    km:["mi",0.621371], kilometre:["mi",0.621371], kilometres:["mi",0.621371],
    kilometer:["mi",0.621371], kilometers:["mi",0.621371],
    kg:["lb",2.20462], kilo:["lb",2.20462], kilos:["lb",2.20462],
    lb:["kg",0.453592], lbs:["kg",0.453592], pound:["kg",0.453592], pounds:["kg",0.453592],
    ft:["cm",30.48], foot:["cm",30.48], feet:["cm",30.48],
    cm:["in",0.393701], m:["ft",3.28084], metre:["ft",3.28084], metres:["ft",3.28084],
    meter:["ft",3.28084], meters:["ft",3.28084],
    "in":["cm",2.54], inch:["cm",2.54], inches:["cm",2.54],
    mph:["km/h",1.60934], kmh:["mph",0.621371]
  };
  var FACTS = {
    "capital of france":"Paris", "capital of japan":"Tokyo", "capital of italy":"Rome",
    "capital of spain":"Madrid", "capital of germany":"Berlin", "capital of england":"London",
    "capital of canada":"Ottawa", "capital of australia":"Canberra", "capital of egypt":"Cairo",
    "capital of brazil":"Brasília", "capital of the united states":"Washington, D.C.",
    "speed of light":"299,792 km/s", "days in a year":"365 (366 leap)"
  };
  var PHRASES = {
    "thank you":{ spanish:"gracias", french:"merci", german:"danke", italian:"grazie", japanese:"arigatō", portuguese:"obrigado" },
    "hello":{ spanish:"hola", french:"bonjour", german:"hallo", italian:"ciao", japanese:"konnichiwa", portuguese:"olá" },
    "goodbye":{ spanish:"adiós", french:"au revoir", german:"auf wiedersehen", italian:"arrivederci", japanese:"sayōnara", portuguese:"tchau" },
    "please":{ spanish:"por favor", french:"s'il vous plaît", german:"bitte", italian:"per favore", japanese:"onegai", portuguese:"por favor" }
  };
  function fmtNum(n) { if (typeof n !== "number" || !isFinite(n)) return null; return String(Math.round(n * 1000) / 1000); }
  function safeMath(expr) {
    var e = " " + expr.toLowerCase() + " ";
    e = e.replace(/\bplus\b/g, "+").replace(/\bminus\b/g, "-")
         .replace(/\btimes\b/g, "*").replace(/×/g, "*").replace(/÷/g, "/")
         .replace(/\bdivided by\b/g, "/").replace(/\bover\b/g, "/")
         .replace(/\bsquared\b/g, "^2").replace(/\bcubed\b/g, "^3")
         .replace(/\^/g, "**")
         .replace(/sqrt\s*\(?\s*([\d.]+)\s*\)?/g, "Math.sqrt($1)");
    var guard = e.replace(/Math\.sqrt/g, "");
    if (/[^-+*/()., \d]/.test(guard)) return null;   // only safe tokens remain
    if (!/\d/.test(guard)) return null;
    try { var v = Function('"use strict";return (' + e + ")")(); return (typeof v === "number" && isFinite(v)) ? v : null; }
    catch (_) { return null; }
  }
  function answerQuery(raw) {
    var q = (raw || "").trim().toLowerCase().replace(/[?.!]+$/, "")
      .replace(/^(hey |ok |okay )?(juno|dreamlayer)[,\s]+/, "").trim();
    if (!q) return null;
    var m = q.match(/([\d.]+)\s*(?:%|percent)\s*of\s*\$?([\d.]+)/);
    if (m) return { primary: fmtNum(parseFloat(m[1]) / 100 * parseFloat(m[2])), sub: m[1] + "% of " + m[2] };
    m = q.match(/(?:([\d.]+)\s*(?:%|percent)\s*)?tip\s*(?:on|for)?\s*\$?([\d.]+)/);
    if (m) { var pct = m[1] ? parseFloat(m[1]) : 18, base = parseFloat(m[2]), tip = pct / 100 * base;
      return { primary: "$" + fmtNum(tip) + " tip", sub: "total $" + fmtNum(base + tip) + " · " + pct + "% on $" + fmtNum(base) }; }
    m = q.match(/(-?[\d.]+)\s*(?:°|deg|degrees)?\s*(celsius|fahrenheit|c|f)\b.*?\b(?:in|to|into|as)?\s*(celsius|fahrenheit|c|f)\b/);
    if (m) { var val = parseFloat(m[1]), from = m[2][0], to = m[3][0];
      var out = from === to ? val : (from === "c" ? val * 9 / 5 + 32 : (val - 32) * 5 / 9);
      return { primary: fmtNum(out) + "°" + to.toUpperCase(), sub: fmtNum(val) + "°" + from.toUpperCase() }; }
    m = q.match(/(-?[\d.]+)\s*([a-z]+)\s*(?:in|to|into|as)\s+([a-z/]+)/);
    if (m && UNITS[m[2]]) { var rule = UNITS[m[2]]; return { primary: fmtNum(parseFloat(m[1]) * rule[1]) + " " + rule[0], sub: fmtNum(parseFloat(m[1])) + " " + m[2] }; }
    m = q.match(/(?:how do you say|say|translate)\s+"?([a-z\s]+?)"?\s+(?:in|to|into)\s+([a-z]+)/);
    if (m) { var pk = PHRASES[m[1].trim()]; if (pk && pk[m[2].trim()]) return { primary: pk[m[2].trim()], sub: '"' + m[1].trim() + '" in ' + m[2].trim() }; }
    for (var k in FACTS) { if (q.indexOf(k) >= 0) return { primary: FACTS[k], sub: k }; }
    if (/\d\s*[-+*/^]|\bsqrt\b|\bsquared\b|\bcubed\b|\btimes\b|\bplus\b|\bminus\b|\bdivided\b/.test(q)) {
      var expr = q.replace(/^(what'?s|what is|whats|calculate|compute|how much is|solve)\s+/, "");
      var mv = safeMath(expr); if (mv != null) return { primary: fmtNum(mv), sub: expr.trim() };
    }
    return null;
  }

  function Sim() {
    this.people = [];            // {id, name, relation, notes[], debts[], last}
    this.waypath = {};           // subject → place
    this.profile = { name: "", prefs: [] };
    this.incognito = false;
    this.figment = null;
    this.lastPerson = null;
    this.card = null;            // current HUD card object (or null → ready)
    this.transcript = [];
    this._faceOf = {};           // look-id → person id (who a face belongs to)
    this.say("juno", "Halo ready. Talk to me.");
  }
  Sim.prototype.say = function (who, line) {
    if (line) { this.transcript.push({ who: who, line: String(line) }); if (this.transcript.length > 40) this.transcript.shift(); }
  };
  Sim.prototype._find = function (name) {
    if (!name) return null;
    var nl = name.trim().toLowerCase();
    var exact = this.people.filter(function (p) { return p.name.toLowerCase() === nl; });
    if (exact.length) return exact[0];
    var first = this.people.filter(function (p) { return p.name.toLowerCase().split(" ")[0] === nl; });
    return first.length === 1 ? first[0] : null;
  };
  Sim.prototype._writeGate = function () { return !this.incognito; };

  Sim.prototype.handleVoice = function (text, look) {
    text = (text || "").trim(); if (!text) return { say: "" };
    this.say("you", text);
    var out = this._route(text, look);
    this.say("juno", out.say);
    return out;
  };

  Sim.prototype._route = function (text, look) {
    // teach Juno about yourself first
    var learned = parseLearn(text);
    if (learned) {
      if (learned.kind === "name") { this.profile.name = learned.value; this._toast("Learned", "Call you " + learned.value, C.teal); return { say: "Got it — I'll call you " + learned.value + "." }; }
      this.profile.prefs.push(learned.value); this._toast("Learned", learned.value, C.teal); return { say: "Noted. I'll remember that." };
    }
    var it = parseIntent(text), a = it.args;
    switch (it.kind) {
      case "timer": case "interval": case "clock": return this._native(it.kind, a);
      case "timer_cancel": return this._cancel();
      case "meet_person": return this._meet(a.who, a.relation, a.note, look);
      case "note_person": return this._note(a.who, a.note, look);
      case "debt": return this._debt(a.who, a.dir, a.what, look);
      case "debt_settle": return this._settle(a.who);
      case "stash": return this._stash(a.subject, a.place);
      case "locate": return this._locate(a.subject);
      case "missed": return { say: "You're all caught up — nothing while you were away." };
      case "brief": return { say: this._brief() };
      case "fact_check": return { say: this._checkClaim(a.claim || text) };
      case "reply": this._toast("REPLY", "to " + a.to + ": " + (a.text || "…"), C.teal); return { say: "Reply to " + a.to + ": “" + (a.text || "") + "” — open Messages to send." };
      case "recall": return { say: this._recallAnswer(a.query) };
      default: {
        var ans = this._answer(text);           // compute on the glass if we honestly can
        return { say: ans != null ? ans : this._ask(a.query) };
      }
    }
  };

  Sim.prototype._native = function (kind, a) {
    if (kind === "clock" && a.mode === "time") { var d = new Date(), h = d.getHours() % 12 || 12; return { say: "It's " + h + ":" + String(d.getMinutes()).padStart(2, "0") + " " + (d.getHours() < 12 ? "AM" : "PM") + "." }; }
    if (!this._writeGate()) return { say: "Not while you're incognito." };
    if (kind === "timer") { if (!a.seconds) return { say: "How long a timer?" }; this.figment = new Figment("timer", a); this.card = null; return { say: "Timer set for " + spoken(a.seconds) + "." }; }
    if (kind === "interval") { if (!a.work || !a.rest) return { say: "How long on and off?" }; this.figment = new Figment("interval", a); this.card = null; var r = a.rounds ? (" for " + a.rounds + " rounds") : " until you hold to stop"; return { say: "Intervals: " + spoken(a.work) + " on, " + spoken(a.rest) + " off" + r + "." }; }
    this.figment = new Figment("clock", a); this.card = null; return { say: "Clock's up. Hold to dismiss it." };
  };
  Sim.prototype._cancel = function () { if (this.figment) { this.figment = null; return { say: "Stopped." }; } return { say: "Nothing running." }; };

  Sim.prototype._meet = function (who, relation, note, look) {
    if (!who) return { say: "Who is this?" };
    if (!this._writeGate()) return { say: "Not while you're incognito." };
    var p = this._find(who);
    if (!p) {
      p = { id: "p_" + this.people.length, name: who, relation: relation || "", notes: [], debts: [], last: Date.now() };
      this.people.push(p);
    }
    if (relation) p.relation = relation;
    if (note) p.notes.push(note);
    if (look && FACES[look] != null) this._faceOf[look] = p.id;   // bind this face → this person
    this.lastPerson = p;
    var seen = look && FACES[look] != null ? " I'll know them next time." : " (name only — no face in view.)";
    return { say: "Good to meet " + who + "." + seen };
  };
  Sim.prototype._note = function (who, note, look) {
    if (!this._writeGate()) return { say: "Not while you're incognito." };
    var p = who ? this._find(who) : (this.lastPerson || this._personForFace(look));
    if (!p) return { say: who ? ("I don't know who " + who + " is yet.") : "Look at someone first, or say their name." };
    p.notes.push(note); this.lastPerson = p;
    return { say: "Got it — I'll remember that about " + p.name + "." };
  };
  Sim.prototype._debt = function (who, dir, what, look) {
    what = (what || "").trim(); if (!what) return { say: "Owes what?" };
    if (!this._writeGate()) return { say: "Not while you're incognito." };
    var p = who ? this._find(who) : (this.lastPerson || this._personForFace(look));
    if (!p) return { say: who ? ("I don't know who " + who + " is yet.") : "Who owes what?" };
    if (dir === "they_owe") { p.debts.push("owes you " + what); return { say: "Noted — " + p.name + " owes you " + what + "." }; }
    p.debts.push("you owe " + what); return { say: "Noted — you owe " + p.name + " " + what + "." };
  };
  Sim.prototype._settle = function (who) {
    var p = this._find(who); if (!p) return { say: "I don't know who " + who + " is yet." };
    p.debts = []; return { say: "Squared up with " + p.name + "." };
  };
  Sim.prototype._stash = function (subject, place) {
    if (!subject) return { say: "Left what where?" };
    if (!this._writeGate()) return { say: "Not while you're incognito." };
    this.waypath[subject.toLowerCase()] = { subject: subject, place: place };
    this.card = null;
    return { say: place ? ("Got it — your " + subject + " is at " + place + ".") : ("Got it — I'll remember your " + subject + ".") };
  };
  Sim.prototype._locate = function (subject) {
    if (!subject) return { say: "Find what?" };
    var key = subject.toLowerCase(), a = this.waypath[key];
    if (!a) { for (var k in this.waypath) { if (k.indexOf(key) >= 0 || key.indexOf(k) >= 0) { a = this.waypath[k]; break; } } }
    if (!a) return { say: "I don't have a spot saved for your " + subject + " yet." };
    var txt = a.place ? ("at " + a.place) : "somewhere you saved it";
    this._toast("WAYPATH", a.subject + " — " + txt, C.teal);
    return { say: "Your " + a.subject + " — " + txt + "." };
  };
  Sim.prototype._recallAnswer = function (q) {
    // "what does Sarah owe me" style — read from social memory
    var name = (q.match(/\b([A-Z][a-z]+)\b/) || [])[1];
    var p = name ? this._find(name) : null;
    if (p && p.debts.length) return p.name + " " + p.debts.join(", ") + ".";
    if (p) return "Nothing open with " + p.name + " right now.";
    return "I don't have anything on that yet — introduce them and I'll keep track.";
  };
  Sim.prototype._answer = function (q) {
    var a = answerQuery(q);
    if (!a || a.primary == null) return null;
    this.figment = null;
    this.card = { type: "answer", eyebrow: "ANSWER", primary: String(a.primary), sub: a.sub || "", shownAt: now() };
    return a.sub ? (a.primary + "  ·  " + a.sub) : String(a.primary);
  };
  // Morning Brief (cards.morning_brief) — the day, flashed on the glass.
  Sim.prototype._brief = function () {
    this.figment = null;
    this.card = { type: "brief", eyebrow: "YOUR DAY",
      primary: "Three meetings, one deadline.",
      detail: "Clear after 3pm.", footer: "next — 10:00 standup", shownAt: now() };
    return "Your day: three meetings, one deadline, clear after three.";
  };
  // Truth Lens / Veritas (cards.fact_check) — a quiet verdict on a claim.
  var FACT_STYLE = { supported: ["VERIFIED", C.green], disputed: ["CHECK THIS", C.amber],
    self_contradiction: ["SAID OTHERWISE", C.coral], unverified: ["UNVERIFIED", C.ghost] };
  Sim.prototype._factCheck = function (verdict, claim, basis, speaker) {
    var s = FACT_STYLE[verdict] || FACT_STYLE.unverified;
    this.figment = null;
    this.card = { type: "fact", verdict: verdict, eyebrow: s[0], color: s[1],
      primary: claim || "—", detail: basis || "", footer: speaker || "",
      flash: (verdict === "disputed" || verdict === "self_contradiction"), shownAt: now() };
    return s[0] + " — " + (claim || "");
  };
  var CLAIMS = {
    "the earth is flat": ["disputed", "The Earth is an oblate spheroid."],
    "the great wall is visible from space": ["disputed", "Not with the naked eye — a persistent myth."],
    "humans only use 10% of their brain": ["disputed", "A myth — you use virtually all of it."],
    "we only use 10% of our brain": ["disputed", "A myth — you use virtually all of it."],
    "water boils at 100": ["supported", "At sea level, yes — 100 °C / 212 °F."],
    "the sun is a star": ["supported", "Yes — a G-type main-sequence star."],
    "lightning never strikes the same place twice": ["disputed", "It does — tall structures get hit often."],
    "goldfish have a three second memory": ["disputed", "They remember for months, actually."]
  };
  Sim.prototype._checkClaim = function (q) {
    var claim = (q || "").trim().replace(/^(?:is it true(?: that)?|is that (?:true|real|correct)|fact.?check|verify|check (?:that|this))\s*/i, "").trim() || q;
    var t = (claim || "").toLowerCase();
    for (var k in CLAIMS) { if (t.indexOf(k) >= 0) { var c = CLAIMS[k]; return this._factCheck(c[0], claim, c[1], "them"); } }
    return this._factCheck("unverified", claim, "Your Brain would check this against the world.", "you");
  };
  Sim.prototype._ask = function (q) {
    var who = this.profile.name ? (", " + this.profile.name) : "";
    var tips = [
      "On the glasses your Brain answers that — files, mail, the web. In this browser demo I answer what I can compute: try “15% of 240”, “5 miles in km”, or “what time is it”.",
      "No Brain wired in here" + who + " — but I can do timers, conversions, Social Lens recall, Waypath, and the Privacy Veil. Introduce someone, or set a timer.",
      "That one needs your Brain. Here I can still count, convert, remember faces, and hold a countdown — what next" + who + "?"
    ];
    this._askN = ((this._askN || 0) + 1);
    return tips[this._askN % tips.length];
  };

  Sim.prototype._personForFace = function (look) {
    if (!look || FACES[look] == null) return null;
    var pid = this._faceOf[look]; if (!pid) return null;
    for (var i = 0; i < this.people.length; i++) if (this.people[i].id === pid) return this.people[i];
    return null;
  };
  Sim.prototype.lookAt = function (look) {
    if (this.incognito) { this.say("juno", "(veiled — I see nothing)"); return { say: "" }; }
    if (!look || FACES[look] == null) { this.say("juno", "(nobody in view)"); return { say: "Nobody in view." }; }
    var p = this._personForFace(look);
    if (!p) { this.say("juno", "I don't know them yet — introduce us."); return { say: "I don't know them yet — introduce us." }; }
    this.lastPerson = p;
    this.card = { type: "recall", name: p.name, relation: p.relation,
      note: p.notes[p.notes.length - 1] || "", debts: p.debts.slice(), shownAt: now() };
    var bits = [p.relation, p.notes[p.notes.length - 1]].filter(Boolean);
    var line = "That's " + p.name + (bits.length ? " — " + bits.join(", ") + "." : ".");
    this.say("juno", line);
    return { say: line };
  };
  Sim.prototype.gesture = function (name) {
    if (this.figment && !this.figment.ended && name === "long") { this.figment = null; return { handled: true }; }
    if (name === "long" && this.card) { this.card = null; return { handled: true }; }
    return { handled: false };
  };
  Sim.prototype.veil = function (on) {
    this.incognito = !!on;
    this.say("juno", on ? "Veil down — I see and keep nothing." : "Veil up. I'm with you again.");
    return { veiled: this.incognito };
  };
  Sim.prototype._toast = function (eyebrow, primary, color) {
    this.card = { type: "toast", eyebrow: eyebrow, primary: primary, color: color || C.teal, until: now() + 6, shownAt: now() };
  };

  Sim.prototype.step = function (dt) {
    if (this.figment) { this.figment.step(dt); if (this.figment.ended) this.figment = null; }
    if (this.card && this.card.type === "toast" && this.card.until && now() > this.card.until) this.card = null;
  };
  Sim.prototype.state = function () {
    return { veiled: this.incognito, people: this.people.map(function (p) { return p.name; }),
      figment: this.figment ? { kind: this.figment.kind } : null, transcript: this.transcript.slice(-16) };
  };

  /* ======================================================================
     4. THE GLASS — canvas renderer (hud/renderer.py, distilled)
     ====================================================================== */
  var SIZE = 256, CX = 128;
  var FONTPX = { hero: 46, xl: 30, lg: 26, md: 20, sm: 15, xs: 12, mono: 12 };

  function Glass(canvas, sim) {
    this.cv = canvas; this.ctx = canvas.getContext("2d"); this.sim = sim;
    this._t0 = now(); this._last = now(); this._raf = 0; this._on = true;
    this.resize();
  }
  Glass.prototype.resize = function () {
    var dpr = Math.min(root.devicePixelRatio || 1, 2);
    var css = this.cv.clientWidth || 320;
    this.cv.width = Math.round(css * dpr); this.cv.height = Math.round(css * dpr);
    this.scale = this.cv.width / SIZE;
    this.ctx.setTransform(this.scale, 0, 0, this.scale, 0, 0);
  };
  Glass.prototype.font = function (tok) { return "600 " + (FONTPX[tok] || 20) + "px ui-monospace, 'SF Mono', Menlo, monospace"; };
  Glass.prototype.text = function (s, x, y, tok, color) {
    var c = this.ctx; c.font = this.font(tok); c.fillStyle = color; c.textAlign = "center"; c.textBaseline = "middle";
    c.fillText(s, x, y);
  };
  Glass.prototype.clip = function () { var c = this.ctx; c.save(); c.beginPath(); c.arc(CX, CX, CX, 0, Math.PI * 2); c.clip(); };

  Glass.prototype.render = function () {
    var c = this.ctx, sim = this.sim, t = now() - this._t0;
    c.setTransform(this.scale, 0, 0, this.scale, 0, 0);
    c.clearRect(0, 0, SIZE, SIZE);
    // opaque disc by default; a translucent bgAlpha lets the glass read as a
    // see-through lens (the environment behind the canvas shows through).
    c.fillStyle = this.bgAlpha != null ? rgba(C.bg, this.bgAlpha) : C.bg;
    c.beginPath(); c.arc(CX, CX, CX, 0, Math.PI * 2); c.fill();
    this.clip();
    // a freshly-triggered card (a glance recall, a waypath/brief toast) briefly
    // interrupts a running figment, then the glass returns to the countdown —
    // the way an active request takes the stage on the device.
    var fresh = sim.card && sim.card.shownAt != null && (now() - sim.card.shownAt) < 5;
    if (sim.incognito) this._veil(t);
    else if (fresh && sim.card.type === "recall") this._recall(sim.card);
    else if (fresh && sim.card.type === "answer") this._answer(sim.card, t);
    else if (fresh && sim.card.type === "fact") this._fact(sim.card, t);
    else if (fresh && sim.card.type === "brief") this._brief(sim.card);
    else if (fresh && sim.card.type === "toast") this._toast(sim.card);
    else if (sim.figment && !sim.figment.ended) this._figment(sim.figment.frame(), t);
    else if (sim.card && sim.card.type === "recall") this._recall(sim.card);
    else if (sim.card && sim.card.type === "answer") this._answer(sim.card, t);
    else if (sim.card && sim.card.type === "fact") this._fact(sim.card, t);
    else if (sim.card && sim.card.type === "brief") this._brief(sim.card);
    else if (sim.card && sim.card.type === "toast") this._toast(sim.card);
    else this._ready(t);
    c.restore();
  };

  Glass.prototype._ready = function (t) {
    var c = this.ctx, br = 0.45 + 0.3 * (0.5 + 0.5 * Math.sin(t * 1.6));
    c.strokeStyle = rgba(C.teal, 0.6 * br); c.lineWidth = 2;
    c.beginPath(); c.arc(CX, CX, 26, 0, Math.PI * 2); c.stroke();
    c.fillStyle = rgba(C.teal, br); c.beginPath(); c.arc(CX, CX, 5, 0, Math.PI * 2); c.fill();
    this.text("listening for what matters", CX, 192, "xs", C.ghost);
  };
  Glass.prototype._figment = function (f, t) {
    if (f.ended) return this._ready(t);
    var c = this.ctx;
    if (f.pulseOn && f.pulseColor) {
      c.strokeStyle = rgba(f.pulseColor, 0.8); c.lineWidth = 3;
      c.beginPath(); c.arc(CX, CX, CX - 8, 0, Math.PI * 2); c.stroke();
      c.strokeStyle = rgba(f.pulseColor, 0.28); c.lineWidth = 6;
      c.beginPath(); c.arc(CX, CX, CX - 15, 0, Math.PI * 2); c.stroke();
    }
    var rowY = [64, 96, 130, 166, 196];
    for (var i = 0; i < f.lines.length; i++) { var ln = f.lines[i]; if (ln.t) this.text(ln.t, CX, rowY[ln.row] || 130, ln.s, ln.c); }
  };
  Glass.prototype._recall = function (card) {
    this.text("FACE RECALL", CX, 70, "sm", C.recall);
    this.text(card.name, CX, 104, "xl", C.text);
    var y = 140;
    if (card.relation) { this.text(card.relation, CX, y, "md", C.teal); y += 28; }
    if (card.debts && card.debts.length) { this.text(card.debts[0], CX, y, "sm", C.coral); y += 24; }
    if (card.note) { this.text(this._clip(card.note, 26), CX, y, "sm", C.text2); }
  };
  Glass.prototype._answer = function (card, t) {
    var c = this.ctx;
    // a soft bloomed cue ring — the "answer on the glass" arriving
    var br = 0.5 + 0.5 * Math.sin((t || 0) * 2.2);
    c.strokeStyle = rgba(C.teal, 0.14 + 0.12 * br); c.lineWidth = 1.5;
    c.beginPath(); c.arc(CX, 66, 4, 0, Math.PI * 2); c.stroke();
    this.text("ANSWER", CX, 66, "sm", C.teal);
    // hero answer — wrap to at most two lines, drop a size if long
    var p = String(card.primary), lines = this._wrap(p, p.length > 14 ? 16 : 12).slice(0, 2);
    var tok = (p.length > 22 || lines.length > 1) ? "lg" : "xl";
    var y = lines.length > 1 ? 104 : 120;
    for (var i = 0; i < lines.length; i++) { this.text(lines[i], CX, y, tok, C.text); y += tok === "xl" ? 34 : 28; }
    // gradient separator + the restated ask
    if (card.sub) {
      c.strokeStyle = rgba(C.border, 0.9); c.lineWidth = 1;
      c.beginPath(); c.moveTo(CX - 46, y + 2); c.lineTo(CX + 46, y + 2); c.stroke();
      var subs = this._wrap(card.sub, 30).slice(0, 2), sy = y + 22;
      for (var j = 0; j < subs.length; j++) { this.text(subs[j], CX, sy, "sm", C.text2); sy += 20; }
    }
  };
  Glass.prototype._wrap = function (str, max) {
    var words = String(str).split(" "), lines = [], cur = "";
    for (var i = 0; i < words.length; i++) {
      var test = (cur + " " + words[i]).trim();
      if (test.length > max && cur) { lines.push(cur); cur = words[i]; } else cur = test;
    }
    if (cur) lines.push(cur);
    return lines;
  };
  // Truth Lens verdict — colored ring dot, eyebrow, separator, claim, basis, footer.
  Glass.prototype._fact = function (card, t) {
    var c = this.ctx, col = card.color || C.ghost;
    var fl = card.flash ? (0.55 + 0.45 * (0.5 + 0.5 * Math.sin((t || 0) * 6))) : 1;
    c.fillStyle = rgba(col, 0.9 * fl); c.beginPath(); c.arc(CX, 54, 6, 0, Math.PI * 2); c.fill();
    this.text(this._clip(card.eyebrow, 26), CX, 84, "sm", col);
    c.strokeStyle = rgba(C.border, 0.9); c.lineWidth = 1;
    c.beginPath(); c.moveTo(CX - 72, 100); c.lineTo(CX + 72, 100); c.stroke();
    var lines = this._wrap(card.primary, 20).slice(0, 2), y = 126;
    for (var i = 0; i < lines.length; i++) { this.text(lines[i], CX, y, "md", C.text); y += 26; }
    if (card.detail) { var d = this._wrap(card.detail, 22).slice(0, 2), dy = y + 8;
      for (var j = 0; j < d.length; j++) { this.text(d[j], CX, dy, "sm", C.text2); dy += 20; } y = dy; }
    if (card.footer) this.text(this._clip(card.footer, 26), CX, Math.max(y + 6, 198), "xs", C.ghost);
  };
  // Morning Brief — YOUR DAY, a short synthesis, the first points beneath.
  Glass.prototype._brief = function (card) {
    var c = this.ctx;
    this.text(card.eyebrow || "YOUR DAY", CX, 62, "sm", C.teal);
    c.strokeStyle = rgba(C.border, 0.9); c.lineWidth = 1;
    c.beginPath(); c.moveTo(CX - 64, 78); c.lineTo(CX + 64, 78); c.stroke();
    var lines = this._wrap(card.primary, 16).slice(0, 3), y = 106;
    for (var i = 0; i < lines.length; i++) { this.text(lines[i], CX, y, "md", C.text); y += 26; }
    if (card.detail) this.text(this._clip(card.detail, 24), CX, y + 10, "sm", C.text2);
    if (card.footer) this.text(this._clip(card.footer, 24), CX, y + 32, "sm", C.ghost);
  };
  Glass.prototype._toast = function (card) {
    this.text(card.eyebrow, CX, 96, "sm", card.color || C.teal);
    var words = String(card.primary).split(" "), lines = [], cur = "";
    for (var i = 0; i < words.length; i++) { var test = (cur + " " + words[i]).trim(); if (test.length > 22 && cur) { lines.push(cur); cur = words[i]; } else cur = test; }
    if (cur) lines.push(cur); lines = lines.slice(0, 3);
    for (var j = 0; j < lines.length; j++) this.text(lines[j], CX, 130 + j * 26, "md", C.text);
  };
  Glass.prototype._veil = function (t) {
    var c = this.ctx, x = CX, y = CX - 6, r = 26;
    c.strokeStyle = rgba(C.coral, 0.9); c.lineWidth = 2; c.beginPath();
    for (var i = 0; i < 6; i++) { var a = Math.PI / 180 * (60 * i - 30), px = x + r * Math.cos(a), py = y + r * Math.sin(a); i ? c.lineTo(px, py) : c.moveTo(px, py); }
    c.closePath(); c.stroke();
    c.fillStyle = rgba(C.coral, 0.9); c.fillRect(x - 8, y - 8, 5, 16); c.fillRect(x + 3, y - 8, 5, 16);
    this.text("PRIVACY VEIL", CX, 176, "sm", C.coral);
    this.text("Nothing is captured", CX, 198, "xs", C.ghost);
  };
  Glass.prototype._clip = function (s, n) { return s.length <= n ? s : s.slice(0, n - 1) + "…"; };

  Glass.prototype.start = function () {
    if (this._raf) return; var self = this;
    (function loop() {
      var t = now(), dt = Math.min(0.1, t - self._last); self._last = t;
      self.sim.step(dt); self.render();
      if (self._on) self._raf = raf(loop);
    })();
  };
  Glass.prototype.stop = function () { this._on = false; if (this._raf) { caf(this._raf); this._raf = 0; } };

  /* ---- helpers ---- */
  function now() { return (root.performance && root.performance.now ? root.performance.now() : Date.now()) / 1000; }
  var raf = root.requestAnimationFrame ? root.requestAnimationFrame.bind(root) : function (f) { return setTimeout(function () { f(); }, 16); };
  var caf = root.cancelAnimationFrame ? root.cancelAnimationFrame.bind(root) : clearTimeout;
  function rgba(hex, a) {
    var n = parseInt(hex.slice(1), 16);
    return "rgba(" + ((n >> 16) & 255) + "," + ((n >> 8) & 255) + "," + (n & 255) + "," + a + ")";
  }

  root.Halo = { Sim: Sim, Glass: Glass, parseIntent: parseIntent, palette: C, FACES: FACES };
})(typeof window !== "undefined" ? window : this);
