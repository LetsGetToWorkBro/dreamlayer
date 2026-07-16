/**
 * The Android feel — haptics and audio speak the same grammar as iOS with
 * platform-appropriate voices:
 *  - notify beats become clean predefined clicks (Android's notificationAsync
 *    is a long waveform buzz — the pocket-pager the vocabulary forbids);
 *  - earcons take DUCKING audio focus so music dips instead of pausing.
 * Platform and native modules are swapped per test via doMock + isolated
 * requires, mirroring platform_parity.test.ts.
 */

type HapticsSpy = {
  impactAsync: jest.Mock;
  notificationAsync: jest.Mock;
  ImpactFeedbackStyle: Record<string, string>;
  NotificationFeedbackType: Record<string, string>;
};

function makeHapticsSpy(): HapticsSpy {
  return {
    impactAsync: jest.fn(),
    notificationAsync: jest.fn(),
    ImpactFeedbackStyle: { Light: "light", Medium: "medium", Heavy: "heavy" },
    NotificationFeedbackType: { Success: "success", Warning: "warning", Error: "error" },
  };
}

// The service requires its native modules LAZILY (at first play()), so the
// doMocks must stay registered for the whole test, not just module load —
// hence resetModules + doMock per test and dontMock in afterEach.
function loadHaptics(os: "ios" | "android", spy: HapticsSpy) {
  jest.resetModules();
  jest.doMock("react-native", () => ({ Platform: { OS: os } }), { virtual: true });
  jest.doMock("expo-haptics", () => spy, { virtual: true });
  return require("../services/haptics") as typeof import("../services/haptics");
}

describe("haptics: notify beats per platform", () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => {
    jest.useRealTimers();
    jest.dontMock("react-native");
    jest.dontMock("expo-haptics");
    jest.resetModules();
  });

  it("iOS keeps the Taptic notification types", () => {
    const spy = makeHapticsSpy();
    const { play } = loadHaptics("ios", spy);
    play("success");
    jest.runAllTimers();
    expect(spy.notificationAsync).toHaveBeenCalledWith("success");
    expect(spy.impactAsync).not.toHaveBeenCalled();
  });

  it("Android speaks success as a rising pair of clicks — never the waveform buzz", () => {
    const spy = makeHapticsSpy();
    const { play } = loadHaptics("android", spy);
    play("success");
    jest.runAllTimers();
    expect(spy.notificationAsync).not.toHaveBeenCalled();
    expect(spy.impactAsync.mock.calls.map((c) => c[0])).toEqual(["light", "medium"]);
  });

  it("Android composites (interrupt = heavy + error) stay clicks and stay inside the pocket rule", () => {
    const spy = makeHapticsSpy();
    const api = loadHaptics("android", spy);
    api.play("interrupt");
    jest.runAllTimers();
    expect(spy.notificationAsync).not.toHaveBeenCalled();
    expect(spy.impactAsync.mock.calls.map((c) => c[0])).toEqual(["heavy", "heavy", "heavy"]);
    for (const beats of Object.values(api.ANDROID_NOTIFY)) {
      for (const b of beats) expect(b.at).toBeLessThanOrEqual(400);
    }
  });

  it("the veil and every impact-only signal are untouched by the mapping", () => {
    const spy = makeHapticsSpy();
    const { play } = loadHaptics("android", spy);
    play("veil_on");
    jest.runAllTimers();
    expect(spy.impactAsync.mock.calls.map((c) => c[0])).toEqual(["heavy", "medium", "light"]);
  });
});

describe("audio: focus policy per platform", () => {
  function loadSound(os: "ios" | "android", audioSpy: Record<string, jest.Mock>) {
    jest.resetModules();
    jest.doMock("react-native", () => ({ Platform: { OS: os } }), { virtual: true });
    jest.doMock("expo-audio", () => audioSpy, { virtual: true });
    return require("../services/sound") as typeof import("../services/sound");
  }
  // fake timers: playEarcon arms a 4 s player-cleanup timeout that would
  // otherwise hold jest open past the run
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => {
    jest.runAllTimers();
    jest.useRealTimers();
    jest.dontMock("react-native");
    jest.dontMock("expo-audio");
    jest.resetModules();
  });

  it("Android ducks others once, foreground-only, never the earpiece", async () => {
    const setAudioModeAsync = jest.fn(() => Promise.resolve());
    const createAudioPlayer = jest.fn(() => ({ play: jest.fn(), remove: jest.fn() }));
    const sound = loadSound("android", { setAudioModeAsync, createAudioPlayer });
    await sound.playEarcon("listen");
    expect(setAudioModeAsync).toHaveBeenCalledTimes(1);
    expect(setAudioModeAsync).toHaveBeenCalledWith({
      interruptionModeAndroid: "duckOthers",
      shouldPlayInBackground: false,
      shouldRouteThroughEarpiece: false,
    });
    expect(createAudioPlayer).toHaveBeenCalled();
  });

  it("iOS never has its audio session touched", async () => {
    const setAudioModeAsync = jest.fn(() => Promise.resolve());
    const createAudioPlayer = jest.fn(() => ({ play: jest.fn(), remove: jest.fn() }));
    const sound = loadSound("ios", { setAudioModeAsync, createAudioPlayer });
    await sound.playEarcon("listen");
    expect(setAudioModeAsync).not.toHaveBeenCalled();
    expect(createAudioPlayer).toHaveBeenCalled();
  });
});
