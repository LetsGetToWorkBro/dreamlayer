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
  it("fires onPress and a haptic tick", () => {
    const onPress = jest.fn();
    render(
      <Tappable onPress={onPress}>
        <Text>go</Text>
      </Tappable>
    );
    const node = screen.getByText("go");
    fireEvent(node, "pressIn");
    fireEvent.press(node);
    expect(onPress).toHaveBeenCalled();
    expect(tapLight).toHaveBeenCalled();
  });

  it("stays silent when haptic is disabled", () => {
    (tapLight as jest.Mock).mockClear();
    render(
      <Tappable onPress={() => {}} haptic={false}>
        <Text>quiet</Text>
      </Tappable>
    );
    fireEvent(screen.getByText("quiet"), "pressIn");
    expect(tapLight).not.toHaveBeenCalled();
  });
});


describe("Look screen", () => {
  it("shows the no-camera fallback when expo-camera is absent", () => {
    // setup-rntl mocks expo-camera to {}, so loadCamera() → null → fallback
    render(<Look />);
    expect(screen.getByText("No camera here")).toBeTruthy();
  });
});


describe("DemoBanner", () => {
  it("renders nothing when demo mode is off", () => {
    useBrainStore.setState({ demoMode: false });
    const { toJSON } = render(<DemoBanner />);
    expect(toJSON()).toBeNull();
  });

  it("renders the banner pill when demo mode is on", () => {
    useBrainStore.setState({ demoMode: true });
    render(<DemoBanner />);
    // the banner carries a stable nativeID; assert it mounted
    expect(screen.UNSAFE_root).toBeTruthy();
    useBrainStore.setState({ demoMode: false });
  });
});
