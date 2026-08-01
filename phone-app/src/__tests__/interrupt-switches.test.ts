/**
 * The seven switches that reached nothing.
 *
 * `setFactCheck`, `setProactiveCards`, `setFocus`, `setCue`, `setWakeSource`,
 * `setWakeFeedback` and `setProactiveAlerts` have shipped in Settings since
 * launch. Every one called `set(...)` and `persist(...)` — that is AsyncStorage
 * — and stopped. Nothing on the Brain, the hub, or the glasses ever read any of
 * them, so seven controls the wearer believed in changed nothing at all.
 *
 * These tests pin the two halves of the fix that can silently rot:
 *   1. the WRITE reaches the Brain, under the Brain's own key name;
 *   2. the READ-BACK exists, because a locally-persisted copy of a value the
 *      Mac panel can also change drifts the moment either side is touched.
 */
import { useBrainStore } from "../state/useBrainStore";

const brain = () => useBrainStore.getState();
const flush = () => new Promise((r) => setTimeout(r, 0));

function connected() {
  useBrainStore.setState({
    macMini: { connected: true, url: "http://mac:8765", token: "t", relayUrl: "" },
    outbox: {},
  } as never);
}

function unpaired() {
  useBrainStore.setState({
    macMini: { connected: false, url: "", token: "", relayUrl: "" }, outbox: {},
  } as never);
}

function posted(f: jest.Mock): Record<string, unknown> {
  const call = f.mock.calls.find((c) => (c[1] as RequestInit)?.method === "POST");
  expect(call).toBeTruthy();
  return JSON.parse(String((call![1] as RequestInit).body));
}

let fetchMock: jest.Mock;

beforeEach(() => {
  fetchMock = jest.fn((_url: string, _opts?: RequestInit) =>
    Promise.resolve({ json: async () => ({ config: {} }) }));
  (global as never as { fetch: unknown }).fetch = fetchMock;
  useBrainStore.setState({
    cues: { event: true, person: true, place: true },
    wakeSources: { voice: true, tap: true, gaze: true, raise: true },
    wakeFeedback: { visual: true, audio: true, haptic: true },
    proactiveCards: true, proactiveAlerts: true, focus: false, factCheck: false,
    demoMode: false,
  } as never);
  connected();
});

describe("each switch writes the Brain's own key", () => {
  it.each([
    ["setProactiveCards", "proactive_cards"],
    ["setProactiveAlerts", "proactive_alerts"],
    ["setFocus", "focus_mode"],
    ["setFactCheck", "fact_check_enabled"],
  ])("%s → %s", async (setter, key) => {
    const fn = (brain() as never as Record<string, (v: boolean) => void>)[setter] as
      (v: boolean) => void;
    fn(false);
    await flush();
    expect(posted(fetchMock)).toMatchObject({ [key]: false });
  });

  it("a cue writes ONE key, not the whole set", async () => {
    /* A whole-list write is how a client drops a cue by accident when two
       switches move close together. */
    brain().setCue("place", false);
    await flush();
    expect(posted(fetchMock)).toEqual({ cue_place: false });
  });

  it("wake sources write a LIST, because that is what the hub applies", async () => {
    brain().setWakeSource("gaze", false);
    await flush();
    expect((posted(fetchMock).wake_sources as string[]).sort())
      .toEqual(["raise", "tap", "voice"]);
  });

  it("turning every wake source off sends an EMPTY list, not nothing", async () => {
    /* "No way to wake me by gesture" has to survive the round trip as itself
       rather than as "unset", or the hub cannot tell it from an older Brain. */
    useBrainStore.setState({
      wakeSources: { voice: false, tap: false, gaze: false, raise: true },
    } as never);
    brain().setWakeSource("raise", false);
    await flush();
    expect(posted(fetchMock).wake_sources).toEqual([]);
  });

  it("wake feedback writes a list too", async () => {
    brain().setWakeFeedback("audio", false);
    await flush();
    expect((posted(fetchMock).wake_feedback as string[]).sort())
      .toEqual(["haptic", "visual"]);
  });
});

describe("they queue like every other Brain switch when it is away", () => {
  it.each([
    ["setFactCheck", "fact_check_enabled"],
    ["setProactiveCards", "proactive_cards"],
  ])("%s survives a tunnel", async (setter, key) => {
    unpaired();
    const fn = (brain() as never as Record<string, (v: boolean) => void>)[setter] as
      (v: boolean) => void;
    fn(false);
    await flush();
    expect(brain().outbox).toMatchObject({ [key]: false });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("the read-back, so the Mac panel and the phone agree", () => {
  it("takes every switch the Brain reports", async () => {
    connected();
    (global as never as { fetch: unknown }).fetch = jest.fn(() =>
      Promise.resolve({
        json: async () => ({
          config: {
            answer_ahead_enabled: true, fact_check_enabled: true,
            proactive_cards: false, proactive_alerts: false, focus_mode: true,
            cue_event: false, cue_person: true, cue_place: false,
            wake_sources: ["voice"], wake_feedback: ["haptic", "visual"],
          },
        }),
      }));
    await brain().hydrateBrainOwned();
    const s = brain();
    expect(s.answerAhead).toBe(true);
    expect(s.factCheck).toBe(true);
    expect(s.proactiveCards).toBe(false);
    expect(s.proactiveAlerts).toBe(false);
    expect(s.focus).toBe(true);
    expect(s.cues).toEqual({ event: false, person: true, place: false });
    expect(s.wakeSources).toEqual({ voice: true, tap: false, gaze: false, raise: false });
    expect(s.wakeFeedback).toEqual({ visual: true, audio: false, haptic: true });
  });

  it("leaves a switch alone when the Brain reports no such key", async () => {
    connected();
    (global as never as { fetch: unknown }).fetch = jest.fn(() =>
      Promise.resolve({ json: async () => ({ config: { focus_mode: true } }) }));
    await brain().hydrateBrainOwned();
    expect(brain().focus).toBe(true);
    expect(brain().proactiveCards).toBe(true);
    expect(brain().cues).toEqual({ event: true, person: true, place: true });
  });

  it("does not half-apply the cue set", async () => {
    /* Three keys, one object. A picker showing a state nothing holds is worse
       than a picker showing a stale one. */
    connected();
    (global as never as { fetch: unknown }).fetch = jest.fn(() =>
      Promise.resolve({ json: async () => ({ config: { cue_event: false } }) }));
    await brain().hydrateBrainOwned();
    expect(brain().cues).toEqual({ event: true, person: true, place: true });
  });

  it("reads an EMPTY wake list as a real answer", async () => {
    connected();
    (global as never as { fetch: unknown }).fetch = jest.fn(() =>
      Promise.resolve({ json: async () => ({ config: { wake_sources: [] } }) }));
    await brain().hydrateBrainOwned();
    expect(brain().wakeSources)
      .toEqual({ voice: false, tap: false, gaze: false, raise: false });
  });

  it("keeps what it last knew when the Brain cannot be reached", async () => {
    connected();
    useBrainStore.setState({ focus: true } as never);
    (global as never as { fetch: unknown }).fetch = jest.fn(() =>
      Promise.reject(new Error("down")));
    await brain().hydrateBrainOwned();
    expect(brain().focus).toBe(true);
  });
});
