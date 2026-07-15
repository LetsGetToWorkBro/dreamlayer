/** Capabilities screen + store (B3, INNOVATION_SESSION Cat 8 #10): the phone's
 * view of the Brain's optional-capability catalog as a visible upgrade path. */
import React from "react";
import { render, screen } from "@testing-library/react-native";

import Capabilities from "../../app/capabilities";
import { useCapabilityStore, CapItem } from "../state/useCapabilityStore";
import { useBrainStore } from "../state/useBrainStore";

const ITEMS: CapItem[] = [
  { key: "asr", tier: "Voice", title: "On-device transcription", state: "missing",
    gain: "transcribes on-device, audio never uploads", impact: 5,
    profiles: ["profile-mac"], extra: "asr" },
  { key: "ecapa", tier: "Social", title: "Speaker fingerprints", state: "missing",
    gain: "real 192-d voiceprints", impact: 4, profiles: ["profile-mac"], extra: "voice" },
  { key: "hnsw", tier: "Memory", title: "Instant recall", state: "active",
    gain: "indexes memories", impact: 4, profiles: [], extra: "memory" },
];

function seed(partial: Partial<ReturnType<typeof useCapabilityStore.getState>>) {
  useCapabilityStore.setState({ load: jest.fn() as never, ...partial });
}

describe("useCapabilityStore", () => {
  it("loads the catalog from the paired Brain and derives learnable/active", async () => {
    useBrainStore.setState({ macMini: { connected: true, url: "http://mac:8765/", token: "tok" } } as never);
    const fakeFetch = jest.fn().mockResolvedValue({
      json: async () => ({ items: ITEMS, summary: { active: 1, missing: 2 } }),
    });
    await useCapabilityStore.getState().load(fakeFetch as never);
    const s = useCapabilityStore.getState();
    expect(s.items).toHaveLength(3);
    // learnable = "missing" only, best gain first
    expect(s.learnable().map((c) => c.key)).toEqual(["asr", "ecapa"]);
    expect(s.activeCount()).toBe(1);
    expect(fakeFetch).toHaveBeenCalledWith(
      "http://mac:8765/dreamlayer/capabilities",
      expect.objectContaining({ headers: expect.anything() }),
    );
  });

  it("reports not-connected when no Brain is paired", async () => {
    useBrainStore.setState({ macMini: { connected: false, url: "", token: "" } } as never);
    await useCapabilityStore.getState().load(jest.fn() as never);
    expect(useCapabilityStore.getState().connected).toBe(false);
    expect(useCapabilityStore.getState().items).toEqual([]);
  });

  it("swallows a fetch failure into an error, staying usable", async () => {
    useBrainStore.setState({ macMini: { connected: true, url: "http://mac", token: "" } } as never);
    await useCapabilityStore.getState().load(jest.fn().mockRejectedValue(new Error("down")) as never);
    expect(useCapabilityStore.getState().error).toContain("down");
    expect(useCapabilityStore.getState().loaded).toBe(true);
  });
});

describe("Capabilities screen", () => {
  it("renders the upgrade path with the highest-impact capability first", async () => {
    seed({ items: ITEMS, loaded: true, connected: true, loading: false, error: null });
    await render(<Capabilities />);
    expect(screen.getByText("Your Brain can also learn to")).toBeTruthy();
    expect(screen.getByText("On-device transcription")).toBeTruthy();
    expect(screen.getByText("1 of 3 active")).toBeTruthy();
  });

  it("shows an empty state when no Brain is paired", async () => {
    seed({ items: [], loaded: true, connected: false });
    await render(<Capabilities />);
    expect(screen.getByText("No Brain paired")).toBeTruthy();
  });
});
