/** Juno component (jest-expo + RNTL): she renders her matte, exposes an
 * accessibility label, re-tints the aura by state, and — when tapped — fires an
 * earcon (cycling through her cue families) plus a caption. The Animated loops
 * run on the native driver (no-ops under jest-expo), so we assert the static
 * surface and the tap contract, not frame values.
 *
 * Isolation notes (RNTL 14 + jest-expo, hard-won): render/unmount are async
 * (concurrent React) and we tear down explicitly in afterEach. Two runtime
 * quirks shape these tests:
 *   1. findByText/waitFor never settles here and hangs the runner — so we never
 *      query the caption from the tree. We assert the caption *text* through the
 *      synchronous `onSpeak` callback instead, which fires in the press handler.
 *   2. Firing several presses in one synchronous tick wedges the concurrent
 *      renderer for the *following* test — so the multi-press cycling check runs
 *      last, where there is nothing after it to corrupt. */
import React from "react";
import { render, fireEvent, cleanup } from "@testing-library/react-native";

// Spy on the earcon engine so a tap can be asserted without pulling in expo-audio
// (a no-op under jest anyway). jest.mock is hoisted above imports, so its factory
// may only close over `mock*`-named vars.
const mockPlayEarcon = jest.fn();
jest.mock("../services/sound", () => ({ playEarcon: (...a: unknown[]) => mockPlayEarcon(...a) }));

import { Juno } from "../ui/components/Juno";

describe("Juno", () => {
  beforeEach(() => mockPlayEarcon.mockClear());
  afterEach(async () => { await cleanup(); });

  it("renders with an accessibility label", async () => {
    const { getByLabelText } = await render(<Juno width={240} state="idle" />);
    expect(getByLabelText("Juno, the DreamLayer assistant")).toBeTruthy();
  });

  it("mounts for every state without throwing", async () => {
    for (const s of ["idle", "thinking", "success"] as const) {
      const { getByLabelText } = await render(<Juno width={200} state={s} />);
      expect(getByLabelText("Juno, the DreamLayer assistant")).toBeTruthy();
      await cleanup();
    }
  });

  it("speaks the first cue (sound + caption) when tapped", async () => {
    const onSpeak = jest.fn();
    const { getByTestId } = await render(<Juno width={240} state="idle" onSpeak={onSpeak} />);
    fireEvent.press(getByTestId("juno-tap"));
    expect(mockPlayEarcon).toHaveBeenCalledTimes(1);
    expect(mockPlayEarcon).toHaveBeenLastCalledWith("hey");   // first family in the cycle
    expect(onSpeak).toHaveBeenLastCalledWith("hey.");         // the matching caption
  });

  it("does not speak when speakOnTap is false", async () => {
    const onSpeak = jest.fn();
    const { getByTestId } = await render(<Juno width={240} state="idle" speakOnTap={false} onSpeak={onSpeak} />);
    fireEvent.press(getByTestId("juno-tap"));
    expect(mockPlayEarcon).not.toHaveBeenCalled();
    expect(onSpeak).not.toHaveBeenCalled();
  });

  // Runs LAST — see the isolation note (multi-press wedges the next test's render).
  it("cycles through her cue families on repeated taps", async () => {
    const onSpeak = jest.fn();
    const { getByTestId } = await render(<Juno width={240} state="idle" onSpeak={onSpeak} />);
    const tap = getByTestId("juno-tap");
    fireEvent.press(tap);   // hey
    fireEvent.press(tap);   // hello (hey family — hey2 is the Hello take)
    fireEvent.press(tap);   // look
    fireEvent.press(tap);   // watch out
    expect(mockPlayEarcon.mock.calls.map((c) => c[0])).toEqual(["hey", "hey", "look", "watchout"]);
    expect(onSpeak.mock.calls.map((c) => c[0])).toEqual(["hey.", "hello.", "look.", "watch out."]);
  });
});
