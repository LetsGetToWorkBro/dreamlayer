/** Pack picker screen (B8): lists packs and marks the active one. */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react-native";

import Packs from "../../app/packs";
import { usePackStore } from "../state/usePackStore";

describe("Packs screen", () => {
  beforeEach(() => usePackStore.setState({ selectedId: "glass" }));

  it("lists the bundled packs with the active one marked", () => {
    render(<Packs />);
    expect(screen.getByText("Glass")).toBeTruthy();
    expect(screen.getByText("Analog")).toBeTruthy();
    expect(screen.getByText("✓ active")).toBeTruthy(); // Glass is active by default
  });

  it("selecting a pack marks it active", () => {
    render(<Packs />);
    fireEvent.press(screen.getByText("Analog"));
    expect(usePackStore.getState().selectedId).toBe("analog");
  });
});
