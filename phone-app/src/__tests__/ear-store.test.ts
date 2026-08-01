/**
 * The ear stack, on the phone.
 *
 * Live captions, the interpreter, the room read and Name Capture each shipped
 * with a switch on the Mac's own web panel and NOTHING on the phone — and
 * `setAnswerAhead` shipped with a switch on the phone that wrote AsyncStorage
 * and never reached the Brain at all. Both shapes are the same defect: a
 * control the wearer believes in that changes nothing.
 *
 * These tests guard the three things this client must not smooth over:
 *   1. a switch being on is not the feature working;
 *   2. the state lives on the Brain, so a failed write does NOT move a switch;
 *   3. unreachable is not off.
 */
import { useEarStore, EAR_SWITCH_DEFAULTS } from "../state/useEarStore";
import { useBrainStore } from "../state/useBrainStore";
import { useConnectionStore } from "../state/useConnectionStore";

const ear = () => useEarStore.getState();

const CONFIG = {
  listen_enabled: true,
  remote_listen_enabled: false,
  captions_enabled: true,
  answer_ahead_enabled: true,
  interpret_enabled: true,
  interpret_target: "en",
  truth_lens_enabled: true,
  intro_capture_enabled: true,
  intro_auto_keep: false,
};

const EAR = {
  listening: true, heard_count: 12,
  interpret: true, can_interpret: true, interpret_proved: false, interpreted_count: 0,
  truth: true, truth_proved: true, truth_reads: 4,
  remote_listening: false,
};

/* Deliberately carries a `name` the real Brain never sends: the assertion
   below is only meaningful if there is a name available to leak. A client that
   spread the payload instead of picking fields would put it on the phone. */
const INTRO = { enabled: true, auto_keep: false, listening: true, pending: true,
                offered: 3, kept: 1, name: "Maya" };

/** Route the three GETs a refresh makes, so a test can vary one of them. */
function routed(over: Record<string, unknown> = {}) {
  const table: Record<string, unknown> = {
    "/dreamlayer/config": { config: CONFIG },
    "/dreamlayer/ear": EAR,
    "/dreamlayer/intro": INTRO,
    ...over,
  };
  return jest.fn((url: string, opts?: RequestInit) => {
    const key = Object.keys(table).find((k) => String(url).includes(k));
    const body = key ? table[key] : {};
    if (opts?.method === "POST") return Promise.resolve({ json: async () => ({ config: CONFIG }) });
    return Promise.resolve({ json: async () => body });
  });
}

beforeEach(() => {
  useBrainStore.setState({
    macMini: { connected: true, url: "http://mac:8765", token: "tok", relayUrl: "" },
  } as never);
  useEarStore.setState({
    loaded: false, reachable: false, saving: false, lastError: "",
    switches: { ...EAR_SWITCH_DEFAULTS },
    runtime: { ...ear().runtime },
    intro: { pending: false, offered: 0, kept: 0 },
  });
});

describe("reading the Brain's truth, not a local guess", () => {
  it("takes the switches from the Brain's config, not from what the phone remembered", async () => {
    (global as never as { fetch: unknown }).fetch = routed();
    await ear().refresh();
    expect(ear().reachable).toBe(true);
    expect(ear().switches.truth_lens_enabled).toBe(true);
    expect(ear().switches.intro_capture_enabled).toBe(true);
    expect(ear().switches.intro_auto_keep).toBe(false);
  });

  it("keeps the opt-in and the runtime fact as separate answers", async () => {
    /* The whole point of the screen. `interpret_enabled` is on and the
       interpreter has NEVER produced a line — a client that merged these into
       one boolean would draw a green switch over silence. */
    (global as never as { fetch: unknown }).fetch = routed();
    await ear().refresh();
    expect(ear().switches.interpret_enabled).toBe(true);
    expect(ear().runtime.interpretProved).toBe(false);
    expect(ear().runtime.truthProved).toBe(true);
    expect(ear().runtime.truthReads).toBe(4);
  });

  it("leaves a key an older Brain never reports at its DEFAULT, not coerced", async () => {
    /* An older Brain that never heard of Name Capture reports no key at all.
       `interpret_target` is the key that can tell the two behaviours apart:
       its default is "en", so a client that coerced `undefined` would leave it
       empty and the interpreter would have no language to speak back in. The
       booleans around it default to false and cannot distinguish, which is
       exactly why the assertion is anchored here. */
    const older = { config: { listen_enabled: true } };
    (global as never as { fetch: unknown }).fetch = routed({ "/dreamlayer/config": older });
    await ear().refresh();
    expect(ear().switches.listen_enabled).toBe(true);
    expect(ear().switches.interpret_target).toBe("en");
    expect(ear().switches.intro_capture_enabled).toBe(EAR_SWITCH_DEFAULTS.intro_capture_enabled);
  });

  it("refuses a value of the wrong type rather than coercing it to on", async () => {
    /* A Brain that answered `"yes"` — or a proxy that stringified the body —
       must not light a privacy-bearing switch. Truthiness is not agreement. */
    const bad = { config: { truth_lens_enabled: "yes", intro_auto_keep: 1 } };
    (global as never as { fetch: unknown }).fetch = routed({ "/dreamlayer/config": bad });
    await ear().refresh();
    expect(ear().switches.truth_lens_enabled).toBe(false);
    expect(ear().switches.intro_auto_keep).toBe(false);
  });

  it("carries the intro COUNTS and never a name", async () => {
    (global as never as { fetch: unknown }).fetch = routed();
    await ear().refresh();
    expect(ear().intro).toEqual({ pending: true, offered: 3, kept: 1 });
    expect(JSON.stringify(ear().intro)).not.toMatch(/[A-Z][a-z]{2,}/);
  });

  it("survives a Brain with no intro route at all", async () => {
    (global as never as { fetch: unknown }).fetch = jest.fn((url: string) => {
      if (String(url).includes("/intro")) return Promise.reject(new Error("404"));
      if (String(url).includes("/config")) return Promise.resolve({ json: async () => ({ config: CONFIG }) });
      return Promise.resolve({ json: async () => EAR });
    });
    await ear().refresh();
    expect(ear().reachable).toBe(true);
    expect(ear().intro.pending).toBe(false);
  });
});

describe("unreachable is not off", () => {
  it("reports unreachable rather than a row of false switches", async () => {
    (global as never as { fetch: unknown }).fetch = jest.fn(() => Promise.reject(new Error("down")));
    await ear().refresh();
    expect(ear().loaded).toBe(true);
    expect(ear().reachable).toBe(false);
  });

  it("reports unreachable rather than off when no Brain is paired", async () => {
    useBrainStore.setState({ macMini: { connected: false, url: "", token: "" } } as never);
    await ear().refresh();
    expect(ear().reachable).toBe(false);
  });
});

describe("the write happens on the Brain", () => {
  it("posts the Brain's own key name, unwrapped", async () => {
    const f = routed();
    (global as never as { fetch: unknown }).fetch = f;
    await ear().set("truth_lens_enabled", true);
    const post = f.mock.calls.find((c) => (c[1] as RequestInit)?.method === "POST");
    expect(post).toBeTruthy();
    expect(String(post![0])).toContain("/dreamlayer/config");
    expect(JSON.parse(String((post![1] as RequestInit).body))).toEqual({ truth_lens_enabled: true });
  });

  it("does NOT move the switch when there is no Brain to take it", async () => {
    useBrainStore.setState({ macMini: { connected: false, url: "", token: "" } } as never);
    const ok = await ear().set("listen_enabled", true);
    expect(ok).toBe(false);
    expect(ear().switches.listen_enabled).toBe(false);
    expect(ear().lastError).toBe("not-connected");
  });

  it("does NOT move the switch when the write fails", async () => {
    (global as never as { fetch: unknown }).fetch = jest.fn(() => Promise.reject(new Error("gone")));
    const ok = await ear().set("intro_capture_enabled", true);
    expect(ok).toBe(false);
    expect(ear().switches.intro_capture_enabled).toBe(false);
    expect(ear().lastError).toBe("unreachable");
  });

  it("re-reads after a refusal rather than believing the request", async () => {
    /* The Brain type-checks config writes and answers 400 with `error`. A
       client that assumed success would leave a switch showing a value the
       Brain never stored. */
    const f = jest.fn((url: string, opts?: RequestInit) => {
      if (opts?.method === "POST") return Promise.resolve({ json: async () => ({ error: "bad type" }) });
      if (String(url).includes("/config")) return Promise.resolve({ json: async () => ({ config: CONFIG }) });
      if (String(url).includes("/ear")) return Promise.resolve({ json: async () => EAR });
      return Promise.resolve({ json: async () => INTRO });
    });
    (global as never as { fetch: unknown }).fetch = f;
    const ok = await ear().set("intro_auto_keep", true);
    expect(ok).toBe(false);
    expect(ear().lastError).toBe("bad type");
    // …and the state now reflects what the Brain actually holds
    expect(ear().switches.intro_auto_keep).toBe(false);
  });

  it("confirms and dismisses an introduction from the phone", async () => {
    const f = routed();
    (global as never as { fetch: unknown }).fetch = f;
    await ear().confirmIntro({ company: "Overpass" });
    const post = f.mock.calls.find(
      (c) => String(c[0]).includes("/dreamlayer/intro") && (c[1] as RequestInit)?.method === "POST");
    expect(JSON.parse(String((post![1] as RequestInit).body)))
      .toEqual({ action: "confirm", company: "Overpass" });
    await ear().dismissIntro();
    const last = f.mock.calls.filter(
      (c) => String(c[0]).includes("/dreamlayer/intro") && (c[1] as RequestInit)?.method === "POST").pop();
    expect(JSON.parse(String((last![1] as RequestInit).body))).toEqual({ action: "dismiss" });
  });
});

describe("answer-ahead reaches the Brain at all", () => {
  it("pushes answer_ahead_enabled instead of only writing local storage", async () => {
    const f = jest.fn((_url: string, _opts?: RequestInit) =>
      Promise.resolve({ json: async () => ({ config: {} }) }));
    (global as never as { fetch: unknown }).fetch = f;
    useBrainStore.setState({
      macMini: { connected: true, url: "http://mac:8765", token: "t", relayUrl: "" },
      outbox: {},
    } as never);
    useBrainStore.getState().setAnswerAhead(true);
    await new Promise((r) => setTimeout(r, 0));
    const post = f.mock.calls.find((c) => (c[1] as RequestInit)?.method === "POST");
    expect(post).toBeTruthy();
    expect(JSON.parse(String((post![1] as RequestInit).body)))
      .toMatchObject({ answer_ahead_enabled: true });
  });

  it("queues it like every other Brain switch when the Brain is away", async () => {
    useBrainStore.setState({
      macMini: { connected: false, url: "", token: "" }, outbox: {},
    } as never);
    useBrainStore.getState().setAnswerAhead(true);
    await new Promise((r) => setTimeout(r, 0));
    expect(useBrainStore.getState().outbox).toMatchObject({ answer_ahead_enabled: true });
  });

  it("reads the switch back from the Brain, so the Mac panel and the phone agree", async () => {
    /* `answerAhead` was a locally-persisted copy of a value the Mac panel can
       change. Without a read-back the Settings switch shows the opposite of
       what the Brain is doing, which is worse than having no switch. */
    useBrainStore.setState({
      macMini: { connected: true, url: "http://mac:8765", token: "t", relayUrl: "" },
      answerAhead: false,
    } as never);
    (global as never as { fetch: unknown }).fetch = jest.fn(() =>
      Promise.resolve({ json: async () => ({ config: { answer_ahead_enabled: true } }) }));
    await useBrainStore.getState().hydrateBrainOwned();
    expect(useBrainStore.getState().answerAhead).toBe(true);
  });

  it("leaves the local value alone when the Brain reports no such key", async () => {
    useBrainStore.setState({
      macMini: { connected: true, url: "http://mac:8765", token: "t", relayUrl: "" },
      answerAhead: true,
    } as never);
    (global as never as { fetch: unknown }).fetch = jest.fn(() =>
      Promise.resolve({ json: async () => ({ config: {} }) }));
    await useBrainStore.getState().hydrateBrainOwned();
    expect(useBrainStore.getState().answerAhead).toBe(true);
  });

  it("reads back when the Brain returns, after the outbox has drained", async () => {
    useBrainStore.setState({
      macMini: { connected: true, url: "http://mac:8765", token: "t", relayUrl: "" },
      answerAhead: false, outbox: {},
    } as never);
    (global as never as { fetch: unknown }).fetch = jest.fn(() =>
      Promise.resolve({ json: async () => ({ config: { answer_ahead_enabled: true } }) }));
    useConnectionStore.getState().onReconnect(() => {});   // ensure the store exists
    await useBrainStore.getState().hydrateBrainOwned();
    expect(useBrainStore.getState().answerAhead).toBe(true);
  });
});
