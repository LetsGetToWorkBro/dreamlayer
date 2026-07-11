/** Juno component (jest-expo + RNTL): she renders her matte, exposes an
 * accessibility label, and re-tints the aura by state. The Animated loops run
 * on the native driver — under jest-expo they're no-ops, so we assert the
 * static surface (label + that the tree mounts for every state) rather than
 * frame values. */
import React from "react";
import { render, screen } from "@testing-library/react-native";

import { Juno } from "../ui/components/Juno";

describe("Juno", () => {
  it("renders with an accessibility label", () => {
    render(<Juno size={120} state="idle" />);
    expect(screen.getByLabelText("Juno, the DreamLayer assistant")).toBeTruthy();
  });

  it("mounts for every state without throwing", () => {
    for (const s of ["idle", "thinking", "success"] as const) {
      const { unmount } = render(<Juno size={100} state={s} />);
      expect(screen.getByLabelText("Juno, the DreamLayer assistant")).toBeTruthy();
      unmount();
    }
  });
});
