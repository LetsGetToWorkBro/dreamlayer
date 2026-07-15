/** Waypath screen (4.7): the one-dot renderer + destination entry. */
import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react-native";

import Waypath, { parseLatLng } from "../../app/waypath";
import { useWaypathStore } from "../state/useWaypathStore";

describe("parseLatLng", () => {
  it("parses 'lat, lng'", async () => {
    expect(parseLatLng("50.12, 10.34")).toEqual({ lat: 50.12, lng: 10.34 });
  });
  it("rejects junk", async () => {
    expect(parseLatLng("nope")).toBeNull();
    expect(parseLatLng("")).toBeNull();
  });
});

describe("Waypath screen", () => {
  it("renders the idle prompt with no destination", async () => {
    useWaypathStore.getState().clear();
    await render(<Waypath />);
    expect(screen.getByText("set a destination to begin.")).toBeTruthy();
    expect(screen.getByLabelText("waypath-ring")).toBeTruthy();
  });

  it("shows the distance to the next turn while navigating", async () => {
    useWaypathStore.setState({
      route: [{ lat: 0, lng: 0 }],
      status: "navigating",
      dot: { angle: 30, distanceM: 1200, arrived: false },
    });
    await render(<Waypath />);
    expect(screen.getByText("1200 m to the next turn")).toBeTruthy();
  });

  it("shows arrival", async () => {
    useWaypathStore.setState({
      route: [{ lat: 0, lng: 0 }],
      status: "arrived",
      dot: { angle: 0, distanceM: 0, arrived: true },
    });
    await render(<Waypath />);
    expect(screen.getByText("✓ arrived")).toBeTruthy();
  });

  it("offers a demo walk that moves the dot when a route exists", async () => {
    jest.useFakeTimers();
    useWaypathStore.setState({
      route: [{ lat: 0, lng: 0 }, { lat: 0.02, lng: 0 }],
      status: "navigating",
      dot: null,
    });
    await render(<Waypath />);
    await fireEvent.press(screen.getByText(/Simulate the walk/));
    act(() => jest.advanceTimersByTime(1500));
    expect(useWaypathStore.getState().dot).not.toBeNull();
    jest.useRealTimers();
  });
});
