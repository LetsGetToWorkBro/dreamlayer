/** Device Vitals store + screen (B11, INNOVATION_SESSION Cat 8 #5): give the
 * glasses' TEL telemetry an audience. */
import React from "react";
import { render, screen } from "@testing-library/react-native";

import Vitals from "../../app/vitals";
import { useVitalsStore } from "../state/useVitalsStore";

const tel = (event: string, payload?: Record<string, unknown>) => ({ t: "TEL", event, ts: 0, payload });

beforeEach(() => {
  useVitalsStore.getState().reset();
});

describe("useVitalsStore.ingest", () => {
  it("folds HEAP watermarks into a trend", async () => {
    const { ingest } = useVitalsStore.getState();
    ingest(tel("HEAP", { kb: 120 }));
    ingest(tel("HEAP", { kb: 140 }));
    const s = useVitalsStore.getState();
    expect(s.heap).toEqual([120, 140]);
    expect(s.lastHeapKb).toBe(140);
  });

  it("counts crashes and keeps the last error", async () => {
    const { ingest } = useVitalsStore.getState();
    ingest(tel("TICK_ERROR", { error: "nil index", count: 3 }));
    const s = useVitalsStore.getState();
    expect(s.crashes).toBe(3);
    expect(s.lastError).toContain("nil index");
  });

  it("tracks card attention + dismiss rate", async () => {
    const { ingest } = useVitalsStore.getState();
    ingest(tel("CARD_SHOWN"));
    ingest(tel("CARD_SHOWN"));
    ingest(tel("CARD_DISMISSED"));
    const s = useVitalsStore.getState();
    expect(s.shown).toBe(2);
    expect(s.dismissed).toBe(1);
    expect(s.dismissRate()).toBeCloseTo(0.5);
  });

  it("counts banishes and follows the veil", async () => {
    const { ingest } = useVitalsStore.getState();
    ingest(tel("FIGMENT_BANISHED"));
    ingest(tel("PRIVACY_VEIL"));
    let s = useVitalsStore.getState();
    expect(s.banished).toBe(1);
    expect(s.veiled).toBe(true);
    ingest(tel("PRIVACY_RESUMED"));
    expect(useVitalsStore.getState().veiled).toBe(false);
  });
});

describe("Device Vitals screen", () => {
  it("shows an empty state before any telemetry", async () => {
    await render(<Vitals />);
    expect(screen.getByText("No telemetry yet")).toBeTruthy();
  });

  it("renders the vitals once telemetry has arrived", async () => {
    const { ingest } = useVitalsStore.getState();
    ingest(tel("HEAP", { kb: 150 }));
    ingest(tel("HEAP", { kb: 100 }));      // now=100, peak=150 (distinct)
    ingest(tel("CARD_SHOWN"));
    ingest(tel("CARD_DISMISSED"));
    await render(<Vitals />);
    expect(screen.getByText("100 KB")).toBeTruthy();   // heap now
    expect(screen.getByText("150 KB")).toBeTruthy();   // peak
    expect(screen.getByText("Dismiss rate")).toBeTruthy();
    expect(screen.getByText("100%")).toBeTruthy();
  });
});
