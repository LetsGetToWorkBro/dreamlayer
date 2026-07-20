/** DreamShell command engine (pure logic). The screen is a thin renderer over
 * this; testing here keeps the commands, the effects, and the dream adventure
 * honest without booting React Native. */
import { run, startDream, type ShellCtx, type DreamState } from "../features/dreamshell";

const shell = (over: Partial<ShellCtx> = {}): ShellCtx => ({ veiled: false, mode: "shell", dream: null, ...over });

describe("DreamShell shell", () => {
  it("help lists the grouped commands", () => {
    const out = run("help", shell());
    const text = out.lines.map((l) => l.t).join("\n");
    expect(text).toContain("ask <anything>");
    expect(text).toContain("type dream");
  });

  it("ask emits an ask effect with the query, not a canned answer", () => {
    const out = run("ask where's the lease?", shell());
    expect(out.effects).toEqual([{ kind: "ask", query: "where's the lease?" }]);
  });

  it("ask with no query just shows usage", () => {
    const out = run("ask", shell());
    expect(out.effects).toBeUndefined();
    expect(out.lines[0]!.t).toContain("usage");
  });

  it("veil toggles to the opposite of the current posture", () => {
    expect(run("veil", shell({ veiled: false })).effects).toEqual([{ kind: "veil", on: true }]);
    expect(run("veil", shell({ veiled: true })).effects).toEqual([{ kind: "veil", on: false }]);
  });

  it("status reflects the veil", () => {
    const up = run("status", shell({ veiled: true })).lines.map((l) => l.t).join(" ");
    expect(up).toContain("veil: up");
    expect(up).toContain("off (veiled)");
  });

  it("nav shortcuts route into the app", () => {
    expect(run("memories", shell()).effects).toEqual([{ kind: "nav", route: "/memories" }]);
    expect(run("caps", shell()).effects).toEqual([{ kind: "nav", route: "/capabilities" }]);
  });

  it("clear and exit fire their effects", () => {
    expect(run("clear", shell()).effects).toEqual([{ kind: "clear" }]);
    expect(run("exit", shell()).effects).toEqual([{ kind: "exit" }]);
  });

  it("the easter eggs are here", () => {
    expect(run("sudo", shell()).lines[0]!.t).toContain("all yours");
    expect(run("42", shell()).lines[0]!.t).toContain("42");
    expect(run("moof", shell()).lines[0]!.t).toContain("Moof");
    expect(run("juno", shell()).effects).toEqual([{ kind: "juno" }]);
    expect(run("matrix", shell()).effects).toEqual([{ kind: "matrix" }]);
    expect(run("hack", shell()).effects).toEqual([{ kind: "glitch" }]);
  });

  it("unknown commands are friendly", () => {
    expect(run("frobnicate", shell()).lines[0]!.t).toContain("unknown");
  });
});

describe("DreamShell dream adventure", () => {
  it("starts in the desk and can be won", () => {
    const start = startDream();
    expect(start.mode).toBe("dream");
    let d: DreamState = start.dream!;
    const step = (cmd: string) => {
      const o = run(cmd, shell({ mode: "dream", dream: d }));
      if (o.dream !== undefined) d = o.dream as DreamState;
      return o;
    };
    // grove shard (north of the desk)
    step("n"); step("take shard");
    expect(d.shards).toBe(1);
    // the shore (east of the desk) has the lantern AND a buried shard
    step("s"); step("e"); step("take lantern");
    expect(d.lantern).toBe(true);
    step("take shard");            // shore shard, now that we have light
    expect(d.shards).toBe(2);
    // the archive (west of the desk) is dark — the lantern makes its shard findable
    step("w"); step("w"); step("take shard");
    expect(d.shards).toBe(3);
    // back to the desk, up through the grove, onto the bridge, then talk to win
    step("e"); step("n"); step("n");
    const win = step("talk juno");
    expect(win.mode).toBe("shell");
    expect(win.lines.map((l) => l.t).join(" ")).toContain("thanks for playing");
    expect(win.effects).toEqual([{ kind: "juno" }]);
  });

  it("won't dig the shore shard in the dark", () => {
    const start = startDream();
    let d = start.dream!;
    const o = run("e", shell({ mode: "dream", dream: d }));   // to the shore
    d = o.dream as DreamState;
    const dig = run("take shard", shell({ mode: "dream", dream: d }));
    expect(dig.lines[0]!.t).toContain("slips through your fingers");
  });

  it("quit returns to the shell", () => {
    const start = startDream();
    const o = run("quit", shell({ mode: "dream", dream: start.dream }));
    expect(o.mode).toBe("shell");
    expect(o.dream).toBeNull();
  });
});
