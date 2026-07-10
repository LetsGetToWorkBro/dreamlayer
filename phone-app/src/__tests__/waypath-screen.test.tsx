/** Waypath screen (4.7): the one-dot renderer + destination entry. */
import React from "react";
import { render, screen } from "@testing-library/react-native";

import Waypath, { parseLatLng } from "../../app/waypath";
import { useWaypathStore } from "../state/useWaypathStore";

describe("parseLatLng", () => {
  it("parses 'lat, lng'", () => {
    expect(parseLatLng("50.12, 10.34")).toEqual({ lat: 50.12, lng: 10.34 });
  });
  it("rejects junk", () => {
    expect(parseLatLng("nope")).toBeNull();
    expect(parseLatLng("")).toBeNull();
  });
});

describe("Waypath screen", () => {
  it("renders the idle prompt with no destination", () => {
    useWaypathStore.getState().clear();
    render(<Waypath />);
    expect(screen.getByText("set a destination to begin.")).toBeTruthy();
    expect(screen.getByLabelText("waypath-ring")).toBeTruthy();
  });

  it("shows the distance to the next turn while navigating", () => {
    useWaypathStore.setState({
      route: [{ lat: 0, lng: 0 }],
      status: "navigating",
      dot: { angle: 30, distanceM: 1200, arrived: false },
    });
    render(<Waypath />);
    expect(screen.getByText("1200 m to the next turn")).toBeTruthy();
  });

  it("shows arrival", () => {
    useWaypathStore.setState({
      route: [{ lat: 0, lng: 0 }],
      status: "arrived",
      dot: { angle: 0, distanceM: 0, arrived: true },
    });
    render(<Waypath />);
    expect(screen.getByText("✓ arrived")).toBeTruthy();
  });
});
