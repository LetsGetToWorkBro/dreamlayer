/**
 * dreamshell.ts — the DreamShell command engine, as pure logic.
 *
 * The website has a terminal; this is its brain on the phone, kept UI-free so it
 * can be unit-tested and driven by app/terminal.tsx. A command returns the lines
 * to print plus optional effects (play a cue, toggle the veil, navigate, run the
 * real Brain `ask`). The adventure ("dream") is a small pure reducer.
 */
export type Tone = "normal" | "bold" | "dim" | "warn" | "coral" | "juno";
export type Line = { t: string; tone?: Tone };

export type Effect =
  | { kind: "clear" }
  | { kind: "exit" }
  | { kind: "veil"; on: boolean }
  | { kind: "nav"; route: string }
  | { kind: "juno" }            // play a Juno cue + light haptic
  | { kind: "haptic" }          // a small buzz
  | { kind: "matrix" }          // the rain flourish
  | { kind: "glitch" }          // a jolt
  | { kind: "ask"; query: string };   // run the real Brain

export type Mode = "shell" | "dream";

export type DreamState = {
  room: string;
  shards: number;
  lantern: boolean;
  taken: Record<string, boolean>;
};

export type ShellCtx = { veiled: boolean; mode: Mode; dream: DreamState | null };
export type Outcome = {
  lines: Line[];
  effects?: Effect[];
  mode?: Mode;                  // a new mode, if it changed
  dream?: DreamState | null;    // new dream state, if it changed
};

const L = (t: string, tone?: Tone): Line => ({ t, tone });

export const BANNER: Line[] = [
  L("DreamShell 8.1 — the layer's command line", "bold"),
  L("brain: reachable   cloud: on device   veil: down"),
  L("type help to see what you can do. type dream to help juno.", "dim"),
  L(""),
];

const HELP: Line[] = [
  L("talk to your brain", "bold"),
  L("  ask <anything>   ask the Brain, in plain words"),
  L("  status           what's on, and which tier answers"),
  L("  caps             optional powers you can switch on"),
  L("  veil             go dark — nothing captured or shown"),
  L("the usual", "bold"),
  L("  help · about · whoami · date · echo · clear · exit"),
  L("and", "bold"),
  L("  type dream. the rest you'll find.", "dim"),
];

const NAV: Record<string, string> = {
  memories: "/memories", people: "/people", brain: "/brain", now: "/now",
  look: "/look", receipts: "/receipts", caps: "/capabilities", plugins: "/plugins",
  vitals: "/vitals", waypath: "/waypath", rewind: "/rewind",
};

// The Juno phrases the tap-to-speak cycles; here they just print (audio via the
// `juno` effect, which the screen plays through the same earcon engine).
const JUNO_LINES = ["hey.", "hello.", "look.", "watch out.", "based.", "uh… ok, then."];
let junoIdx = 0;

// ---------------------------------------------------------------------------
// dream — a tiny adventure, the same one the website ships, kept on-device.
// ---------------------------------------------------------------------------
type Room = {
  name: string; desc: string; exits: Record<string, string>;
  shard?: string; dark?: boolean; lanternHere?: boolean;
};
const ROOMS: Record<string, Room> = {
  desk: { name: "the desk at dusk", desc: "a platinum desk under a violet sky. paths lead north to a crystal grove, east to a shore of static, west to the archive.", exits: { n: "grove", e: "shore", w: "archive" } },
  grove: { name: "the crystal grove", desc: "teal crystals chime. north, a thin bridge disappears into mist.", exits: { s: "desk", n: "bridge" }, shard: "a shard glints between two crystals." },
  shore: { name: "the shore of static", desc: "a sea of grey noise laps at nothing. an unlit lantern figment sits in the sand.", exits: { w: "desk" }, lanternHere: true, shard: "something is buried under the static — too dim to see." },
  archive: { name: "the archive", desc: "shelves of memories, each labeled in chicago. it is very dark in here.", exits: { e: "desk" }, dark: true, shard: "a shard rests on the third shelf." },
  bridge: { name: "the veil bridge", desc: "juno waits at the middle of the bridge, holding out her hands.", exits: { s: "grove" } },
};

function look(d: DreamState): Line[] {
  const r = ROOMS[d.room]!;
  const out: Line[] = [L(r.name, "bold"), L(r.desc)];
  if (r.dark && !d.lantern) out.push(L("you can't make out much without a light.", "dim"));
  else if (r.shard && !d.taken[d.room]) {
    out.push(d.room === "shore" && !d.lantern ? L(r.shard, "dim") : L(r.shard, "warn"));
  }
  if (d.room === "bridge") {
    out.push(d.shards === 3 ? L('juno: "you found them. talk to me."', "bold")
                            : L(`juno: "${d.shards} of 3. the rest are still out there."`, "bold"));
  }
  return out;
}

export function startDream(): Outcome {
  const dream: DreamState = { room: "desk", shards: 0, lantern: false, taken: {} };
  return {
    mode: "dream", dream,
    lines: [
      L(""),
      L("— d r e a m —", "bold"),
      L("the desk at dusk. juno hovers, wings catching the last light."),
      L('juno: "a memory came apart — three shards, scattered where i dream. find them and meet me at the veil bridge."', "bold"),
      L("verbs: n/s/e/w · look · take <thing> · use lantern · talk juno · inv · quit", "dim"),
      ...look(dream),
    ],
  };
}

function dreamExec(raw: string, d: DreamState): Outcome {
  const line = raw.trim().toLowerCase();
  if (!line) return { lines: [] };
  const p = line.split(/\s+/);
  const go: Record<string, string> = { n: "n", north: "n", s: "s", south: "s", e: "e", east: "e", w: "w", west: "w", go: "" };
  let v = p[0]!;
  if (v === "go" && p[1]) v = go[p[1]] ?? p[1];
  else if (go[v]) v = go[v]!;

  if (v === "quit") return { mode: "shell", dream: null, lines: [L("the dream folds shut. the desk returns.")] };
  if (v === "inv" || v === "inventory")
    return { lines: [L("you carry: " + (d.shards ? `${d.shards} shard${d.shards > 1 ? "s" : ""}` : "nothing") + (d.lantern ? ", a lit lantern figment" : ""))] };
  if (v === "score") return { lines: [L(`${d.shards} / 3 shards`)] };
  if (v === "look" || v === "l") return { lines: look(d) };
  if (["n", "s", "e", "w"].includes(v)) {
    const r = ROOMS[d.room]!;
    if (r.exits[v]) { const nd = { ...d, room: r.exits[v]! }; return { dream: nd, lines: look(nd) }; }
    return { lines: [L("you can't go that way.")] };
  }
  if (v === "take") {
    const r = ROOMS[d.room]!; const what = p.slice(1).join(" ");
    if (/lantern/.test(what) && r.lanternHere && !d.lantern)
      return { dream: { ...d, lantern: true }, lines: [L("you pick up the lantern figment. it proves itself safe, then lights.")] };
    if (/shard/.test(what) && r.shard && !d.taken[d.room]) {
      if (r.dark && !d.lantern) return { lines: [L("too dark to find anything.")] };
      if (d.room === "shore" && !d.lantern) return { lines: [L("you dig at the static. it slips through your fingers. maybe with a light…", "dim")] };
      const nd = { ...d, shards: d.shards + 1, taken: { ...d.taken, [d.room]: true } };
      return { dream: nd, lines: [L(`you lift the shard. it hums like a remembered song. (${nd.shards} / 3)`, "bold")] };
    }
    return { lines: [L(`there's no ${what || "that"} to take here.`)] };
  }
  if (v === "use" && /lantern/.test(line))
    return { lines: [L(d.lantern ? "the lantern glows steady. dark places won't be dark." : "you don't have a lantern.")] };
  if (v === "talk") {
    if (d.room !== "bridge") return { lines: [L('juno\'s voice, from somewhere: "the bridge. north of the grove."')] };
    if (d.shards < 3) return { lines: [L(`juno: "${d.shards} of 3. i'll wait. i'm good at waiting."`, "bold")] };
    return {
      mode: "shell", dream: null, effects: [{ kind: "juno" }],
      lines: [
        L("juno presses the shards together. the seams vanish.", "bold"),
        L('juno: "kept. not uploaded — kept. that\'s the difference."', "bold"),
        L("you wake at the desk."),
        L(""),
        L("— thanks for playing · 3 / 3 —", "bold"),
      ],
    };
  }
  if (v === "xyzzy") return { lines: [L("a hollow voice says: fool.", "dim")] };   // classic
  return { lines: [L("try: n/s/e/w · look · take · use lantern · talk juno · inv · quit", "dim")] };
}

// ---------------------------------------------------------------------------
// the shell
// ---------------------------------------------------------------------------
export function run(raw: string, ctx: ShellCtx): Outcome {
  if (ctx.mode === "dream" && ctx.dream) return dreamExec(raw, ctx.dream);

  const line = raw.trim();
  if (!line) return { lines: [] };
  const p = line.split(/\s+/);
  const c = p[0]!.toLowerCase();
  const rest = line.slice(p[0]!.length).trim();

  switch (c) {
    case "help": case "?": return { lines: HELP };
    case "clear": return { lines: [], effects: [{ kind: "clear" }] };
    case "about": return { lines: [L("DreamLayer — a private memory layer for smart glasses. This app is its face; the Brain runs on your machine. DreamShell is its command line.")] };
    case "whoami": return { lines: [L("a person whose memory is about to get better.")] };
    case "date": return { lines: [L(new Date().toString())] };
    case "echo": return { lines: [L(rest)] };
    case "exit": return { lines: [L("goodbye…")], effects: [{ kind: "exit" }] };
    case "veil": {
      const on = !ctx.veiled;
      return { lines: [L(on ? "veil down. nothing leaves this screen." : "veil lifted.", on ? "dim" : "normal")], effects: [{ kind: "veil", on }] };
    }
    case "ask":
      if (!rest) return { lines: [L("usage: ask where's the lease?", "dim")] };
      return { lines: [L("thinking…", "dim")], effects: [{ kind: "ask", query: rest }] };
    case "status": case "brain":
      return { lines: [
        L("brain reachable · on-device", "bold"),
        L("veil: " + (ctx.veiled ? "up" : "down") + " · cloud: " + (ctx.veiled ? "off (veiled)" : "your call")),
        L("everything here runs on your devices.", "dim"),
      ] };
    case "caps": case "capabilities":
      return { lines: [L("opening Capabilities…", "dim")], effects: [{ kind: "nav", route: "/capabilities" }] };
    case "juno": {
      const say = JUNO_LINES[junoIdx++ % JUNO_LINES.length]!;
      return { lines: [L("juno: " + say, "juno")], effects: [{ kind: "juno" }] };
    }
    case "matrix": case "rain":
      return { lines: [L("wake up…", "dim")], effects: [{ kind: "matrix" }] };
    case "glitch":
      return { lines: [L("— signal recovered —", "dim")], effects: [{ kind: "glitch" }] };
    case "buzz": case "haptic":
      return { lines: [L("*buzz*", "dim")], effects: [{ kind: "haptic" }] };
    case "sudo":
      return { lines: [L("the layer has no root to sudo to. it's already all yours.")] };
    case "hack":
      return { lines: [
        L("accessing mainframe…", "warn"), L("bypassing firewall…", "warn"), L("decrypting…", "warn"),
        L("0wned.", "warn"), L(""), L("just kidding. nothing here is hidden from you — it's your Brain."),
      ], effects: [{ kind: "glitch" }] };
    case "moof": case "clarus":
      return { lines: [L("Moof! 🐮", "bold"), L("the dogcow says hi. (ask a Mac historian.)", "dim")] };
    case "42": case "answer": case "theanswer":
      return { lines: [L("42. but you knew that.")] };
    case "sosumi":
      return { lines: [L("beep."), L("(the lawyers kept the rest.)", "dim")] };
    case "ls": case "tree":
      return { lines: [
        L("."), L("├─ memories/   kept, indexed, yours", "dim"),
        L("├─ people/     only those who introduced themselves", "dim"),
        L("├─ promises/   what you said you'd do", "dim"),
        L("└─ veil        the off switch for all of it", "dim"),
      ] };
    case "dream": return startDream();
    default:
      if (NAV[c]) return { lines: [L("opening " + c + "…", "dim")], effects: [{ kind: "nav", route: NAV[c]! }] };
      return { lines: [L("? unknown: " + c + " — try help", "warn")] };
  }
}

export const COMPLETIONS = [
  "help", "ask ", "status", "caps", "veil", "about", "whoami", "date", "echo ",
  "clear", "exit", "dream", "matrix", "glitch", "juno", "memories", "people", "brain",
];
