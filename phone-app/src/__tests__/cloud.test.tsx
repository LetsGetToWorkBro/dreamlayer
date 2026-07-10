/** "What the cloud can see" panel + store (B16, INNOVATION_SESSION Cat 6): the
 * trust centerpiece — render the opaque byte-shapes and name what it can't see. */
import React from "react";
import { render, screen } from "@testing-library/react-native";

import Cloud from "../../app/cloud";
import { useCloudViewStore } from "../state/useCloudViewStore";
import { useBrainStore } from "../state/useBrainStore";

const OFF = {
  enabled: false,
  vault: null,
  relay: { rooms: [] },
  listings: 0,
  cannot_see: ["your memories — never leave the device unencrypted"],
};

function seed(partial: Partial<ReturnType<typeof useCloudViewStore.getState>>) {
  useCloudViewStore.setState({ load: jest.fn() as never, ...partial });
}

describe("useCloudViewStore", () => {
  it("fetches the cloud view from the paired Brain", async () => {
    useBrainStore.setState({ macMini: { connected: true, url: "http://mac:8765", token: "t" } } as never);
    const fakeFetch = jest.fn().mockResolvedValue({ json: async () => OFF });
    await useCloudViewStore.getState().load(fakeFetch as never);
    const s = useCloudViewStore.getState();
    expect(s.connected).toBe(true);
    expect(s.enabled).toBe(false);
    expect(s.cannot_see.length).toBeGreaterThan(0);
    expect(fakeFetch).toHaveBeenCalledWith("http://mac:8765/dreamlayer/cloud", expect.anything());
  });

  it("reports not-connected without a Brain", async () => {
    useBrainStore.setState({ macMini: { connected: false, url: "", token: "" } } as never);
    await useCloudViewStore.getState().load(jest.fn() as never);
    expect(useCloudViewStore.getState().connected).toBe(false);
  });
});

describe("Cloud panel", () => {
  it("shows 'holds nothing' + the guarantees when cloud is off", () => {
    seed({ ...OFF, loaded: true, connected: true });
    render(<Cloud />);
    expect(screen.getByText("Cloud is off")).toBeTruthy();
    expect(screen.getByText("What it can never see")).toBeTruthy();
  });

  it("renders the opaque shapes when cloud is on", () => {
    seed({
      enabled: true,
      vault: { bytes: 2_300_000, last_backup_ts: 0 },
      relay: { rooms: [{ id: "7f3a9c1b", members: 2 }] },
      listings: 3,
      cannot_see: ["who you are — only a room id"],
      loaded: true,
      connected: true,
    });
    render(<Cloud />);
    expect(screen.getByText(/2\.3 MB of ciphertext/)).toBeTruthy();
    expect(screen.getByText(/1 room/)).toBeTruthy();
    expect(screen.getByText("What it can never see")).toBeTruthy();
  });
});
