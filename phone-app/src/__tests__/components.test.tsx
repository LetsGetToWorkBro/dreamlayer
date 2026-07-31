/** Component tests (jest-expo + RNTL): real RN rendering of the screens/units
 * that carry logic — the haptic touch primitive, the Look camera fallback, the
 * demo banner's on/off gate, and the accessibility contract (reduce motion +
 * screen-reader labels). Kept focused so the RN transform stack only runs where
 * a rendered assertion adds coverage the logic tests can't.
 *
 * Reduce motion is asserted on RESOLVED PROPS: Animated resolves its values
 * into the style object at render time, so the entrance animation's first
 * frame is readable straight off the tree — opacity 0 / rise 10 / scale 0.94
 * when motion is allowed, at-rest when it isn't. No device, no frame clock. */
import React from "react";
import { AccessibilityInfo, Text } from "react-native";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react-native";

import { Tappable } from "../ui/components/Tappable";
import { Card } from "../ui/components/Card";
import { MenuBar } from "../ui/components/MenuBar";
import { ScreenHeader } from "../ui/components/ScreenHeader";
import { reduceMotionWatcherCount } from "../ui/anim";
import {
  motion, motionDuration, setReduceMotion, subscribeReduceMotion,
} from "../ui/theme/motion";
import { tapLight } from "../services/haptics";
import Look from "../../app/look";
import { DemoBanner } from "../ui/components/DemoBanner";
import { useBrainStore } from "../state/useBrainStore";

jest.mock("../services/haptics", () => ({
  tapLight: jest.fn(),
  tapMedium: jest.fn(),
  play: jest.fn(),
}));


describe("Tappable", () => {
  it("fires onPress and a haptic tick", async () => {
    const onPress = jest.fn();
    await render(
      <Tappable onPress={onPress}>
        <Text>go</Text>
      </Tappable>
    );
    const node = screen.getByText("go");
    await fireEvent(node, "pressIn");
    await fireEvent.press(node);
    expect(onPress).toHaveBeenCalled();
    expect(tapLight).toHaveBeenCalled();
  });

  it("stays silent when haptic is disabled", async () => {
    (tapLight as jest.Mock).mockClear();
    await render(
      <Tappable onPress={() => {}} haptic={false}>
        <Text>quiet</Text>
      </Tappable>
    );
    await fireEvent(screen.getByText("quiet"), "pressIn");
    expect(tapLight).not.toHaveBeenCalled();
  });

  // P2-14: the one touch primitive is what makes (or breaks) screen-reader
  // access app-wide — every Tappable must be a labeled, stateful button.
  it("announces itself as a button to screen readers", async () => {
    await render(
      <Tappable onPress={() => {}}>
        <Text>go</Text>
      </Tappable>
    );
    expect(screen.getByRole("button")).toBeTruthy();
  });

  it("carries an explicit label for icon-only surfaces", async () => {
    await render(
      <Tappable onPress={() => {}} accessibilityLabel="Ask your Brain">
        <Text>{"↳"}</Text>
      </Tappable>
    );
    expect(screen.getByRole("button", { name: "Ask your Brain" })).toBeTruthy();
  });

  it("reports its disabled state", async () => {
    await render(
      <Tappable onPress={() => {}} disabled>
        <Text>held</Text>
      </Tappable>
    );
    // RNTL's role query honours accessibilityState — a disabled-aware query
    // only matches when the state is actually exposed to the a11y tree
    expect(screen.getByRole("button", { disabled: true })).toBeTruthy();
  });
});


describe("Look screen", () => {
  it("shows the no-camera fallback when expo-camera is absent", async () => {
    // setup-rntl mocks expo-camera to {}, so loadCamera() → null → fallback
    await render(<Look />);
    expect(screen.getByText("No camera here")).toBeTruthy();
  });
});


/* ------------------------------------------------------- reduce motion --
 * The OS setting reaches the app through ONE subscription (src/ui/anim.ts)
 * and ONE flag (src/ui/theme/motion.ts). These tests stand in for the OS by
 * spying on AccessibilityInfo, which is also the only way to prove the
 * subscription is released — a leaked listener shows up as a watcher count
 * that never returns to 0. */

type ReduceHandler = (on: boolean) => void;

/** Stand in for the OS: capture the reduceMotionChanged handler and the
 * subscription we are expected to hand back on teardown. */
function fakeOs(enabled = false) {
  const remove = jest.fn();
  let handler: ReduceHandler | undefined;
  const add = jest
    .spyOn(AccessibilityInfo, "addEventListener")
    .mockImplementation(((_event: string, h: ReduceHandler) => {
      handler = h;
      return { remove } as never;
    }) as never);
  const query = jest
    .spyOn(AccessibilityInfo, "isReduceMotionEnabled")
    .mockResolvedValue(enabled);
  // jest.spyOn hands back the SAME mock when a property is already spied, so
  // clear the history explicitly rather than trusting a cross-test restore
  add.mockClear();
  query.mockClear();
  return {
    add, query, remove,
    /** the OS flipping the setting under a running app */
    flip: async (on: boolean) => { await act(async () => { handler?.(on); }); },
  };
}

/** the entrance animation's resolved style, straight off the rendered tree */
const entranceStyle = (): unknown => screen.toJSON()?.props.style;

const AT_REST = { opacity: 1, transform: [{ translateY: 0 }, { scale: 1 }] };
const FIRST_FRAME = { opacity: 0, transform: [{ translateY: 10 }, { scale: 0.94 }] };

describe("reduce motion", () => {
  afterEach(async () => {
    await cleanup();
    jest.restoreAllMocks();
    setReduceMotion(false);
  });

  it("collapses every duration to instant", () => {
    setReduceMotion(false);
    expect(motionDuration(motion.base)).toBe(motion.base);
    setReduceMotion(true);
    expect(motionDuration(motion.base)).toBe(0);
    expect(motionDuration(200)).toBe(0);
  });

  it("tells its subscribers, and stops when they leave", () => {
    const heard: boolean[] = [];
    const unsubscribe = subscribeReduceMotion((on) => heard.push(on));
    setReduceMotion(true);
    setReduceMotion(true);   // no change, no notification
    setReduceMotion(false);
    unsubscribe();
    setReduceMotion(true);
    expect(heard).toEqual([true, false]);
    expect(motion.reduceMotion).toBe(true);
  });

  it("plays the entrance when motion is allowed", async () => {
    fakeOs(false);
    await render(<ScreenHeader title="Waypath" back={false} />);
    expect(entranceStyle()).toMatchObject(FIRST_FRAME);
  });

  it("mounts a screen at rest when the OS asked for less motion", async () => {
    fakeOs(true);
    setReduceMotion(true);
    await render(<ScreenHeader title="Waypath" back={false} />);
    expect(entranceStyle()).toMatchObject(AT_REST);
  });

  it("reads the OS setting on mount, without being told", async () => {
    fakeOs(true);
    expect(motion.reduceMotion).toBe(false);
    await render(<ScreenHeader title="Waypath" back={false} />);
    await act(async () => {});   // let isReduceMotionEnabled() settle
    expect(motion.reduceMotion).toBe(true);
  });

  it("collapses a running screen when the OS flips mid-session", async () => {
    const os = fakeOs(false);
    await render(<ScreenHeader title="Waypath" back={false} />);
    expect(entranceStyle()).toMatchObject(FIRST_FRAME);
    await os.flip(true);
    await screen.rerender(<ScreenHeader title="Waypath" back={false} />);
    expect(entranceStyle()).toMatchObject(AT_REST);
  });

  it("keeps ONE OS subscription for the whole app and releases it", async () => {
    const os = fakeOs(false);
    await render(
      <>
        <ScreenHeader title="A" back={false} />
        <ScreenHeader title="B" back={false} />
      </>
    );
    expect(os.add).toHaveBeenCalledTimes(1);
    expect(os.add).toHaveBeenCalledWith("reduceMotionChanged", expect.any(Function));
    expect(reduceMotionWatcherCount()).toBe(2);
    expect(os.remove).not.toHaveBeenCalled();   // one leaving must not deafen the other

    await cleanup();
    // RN 0.86 has no removeEventListener — the subscription IS the handle
    expect(os.remove).toHaveBeenCalledTimes(1);
    expect(reduceMotionWatcherCount()).toBe(0);
  });

  it("still shades a window when the roll-up is switched off", async () => {
    fakeOs(true);
    setReduceMotion(true);
    await render(<Card title="Panel"><Text>body</Text></Card>);
    const bar = screen.getByRole("button", { name: "Panel — WindowShade" });
    expect(screen.getByText("body")).toBeTruthy();
    await fireEvent.press(bar);
    expect(screen.queryByText("body")).toBeNull();
    expect(screen.getByRole("button", { expanded: false })).toBeTruthy();
  });
});


/* ------------------------------------------------ screen-reader labels --
 * Chrome that only speaks in pixels — a window title, a back chevron, a
 * clock — is silent to VoiceOver/TalkBack unless it says what it is. */
describe("screen-reader labels", () => {
  afterEach(async () => { await cleanup(); setReduceMotion(false); });

  it("announces the screen title as a heading", async () => {
    await render(<ScreenHeader title="Waypath" back={false} />);
    expect(screen.getByRole("header", { name: "Waypath" })).toBeTruthy();
  });

  it("announces the back control", async () => {
    await render(<ScreenHeader title="Waypath" back />);
    expect(screen.getByRole("button", { name: "Back" })).toBeTruthy();
  });

  it("announces a plain window title as a heading", async () => {
    await render(<Card title="Verification" shade={false}><Text>body</Text></Card>);
    expect(screen.getByRole("header", { name: "Verification" })).toBeTruthy();
  });

  it("announces a WindowShade bar as a button that reports its state", async () => {
    await render(<Card title="Panel"><Text>body</Text></Card>);
    expect(screen.getByRole("button", { name: "Panel — WindowShade", expanded: true })).toBeTruthy();
    await fireEvent.press(screen.getByRole("button", { name: "Panel — WindowShade" }));
    expect(screen.getByRole("button", { name: "Panel — WindowShade", expanded: false })).toBeTruthy();
  });

  it("says what the menu bar clock is", async () => {
    await render(<MenuBar />);
    // the bare time reads as a stray number out of context
    expect(screen.getByLabelText(/^Time, \d{1,2}:\d{2} [AP]M$/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "DreamLayer home" })).toBeTruthy();
  });
});


describe("DemoBanner", () => {
  it("renders nothing when demo mode is off", async () => {
    useBrainStore.setState({ demoMode: false });
    // RNTL 14: render is async (concurrent React) — await it before reading
    const { toJSON } = await render(<DemoBanner />);
    expect(toJSON()).toBeNull();
  });

  it("renders the banner pill when demo mode is on", async () => {
    useBrainStore.setState({ demoMode: true });
    await render(<DemoBanner />);
    // RNTL 14 dropped UNSAFE_root; a non-null tree proves the pill mounted
    expect(screen.toJSON()).not.toBeNull();
    useBrainStore.setState({ demoMode: false });
  });
});
