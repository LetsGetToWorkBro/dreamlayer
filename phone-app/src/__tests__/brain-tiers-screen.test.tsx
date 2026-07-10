/** Brain ceremony screen (3.1): renders the ladder + a swap control. */
import React from "react";
import { render, screen, fireEvent } from "@testing-library/react-native";

import BrainTiers from "../../app/brain-tiers";
import { useBrainTiersStore } from "../state/useBrainTiersStore";
import { useBrainStore } from "../state/useBrainStore";

describe("Brain tiers screen", () => {
  beforeEach(() => {
    useBrainTiersStore.setState({
      model: "claude-sonnet-5", cloud_provider: "anthropic", cloud: true,
      incognito: false, active_tier: "device", loaded: true, connected: true,
      tiers: [
        { id: "device", name: "On-device", note: "small, instant", enabled: true, latency_ms: 12, answered: 3, failed: 0, reliability: 1, seen: true },
        { id: "mac_mini", name: "Mac mini", note: "bigger local", enabled: true, latency_ms: 90, answered: 5, failed: 0, reliability: 1, seen: true },
        { id: "cloud", name: "Cloud", note: "hardest asks", enabled: true, latency_ms: null, answered: 0, failed: 0, reliability: null, seen: false },
      ],
      load: async () => {},
    } as never);
    useBrainStore.setState({ cloud: true, incognito: false } as never);
  });

  it("shows the loaded cartridge and the tier ladder with latency", () => {
    render(<BrainTiers />);
    expect(screen.getByText("claude-sonnet-5")).toBeTruthy();
    expect(screen.getByText("On-device")).toBeTruthy();
    expect(screen.getByText("Mac mini")).toBeTruthy();
    expect(screen.getByText("12 ms")).toBeTruthy();
    expect(screen.getByText("90 ms")).toBeTruthy();
    expect(screen.getByText("not used yet")).toBeTruthy();   // cloud never answered
  });

  it("toggling the cloud switch calls the brain store", () => {
    const setCloud = jest.fn();
    useBrainStore.setState({ setCloud } as never);
    render(<BrainTiers />);
    const sw = screen.UNSAFE_getAllByType(require("react-native").Switch)[0];
    fireEvent(sw, "valueChange", false);
    expect(setCloud).toHaveBeenCalledWith(false);
  });
});
