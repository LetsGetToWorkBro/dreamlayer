/** Component tests (jest-expo + RNTL): real RN rendering of the screens/units
 * that carry logic — the haptic touch primitive, the Look camera fallback, and
 * the demo banner's on/off gate. Kept focused so the RN transform stack only
 * runs where a rendered assertion adds coverage the logic tests can't. */
import React from "react";
import { Text } from "react-native";
import { fireEvent, render, screen } from "@testing-library/react-native";

import { Tappable } from "../ui/components/Tappable";
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
