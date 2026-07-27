/** OSRM routing adapter + the Waypath store (4.7). Fetch is injected — no live
 * network, no maps SDK. */
import { fetchRoute, OSRM_DEMO } from "../nav/osrm";
import { useBrainStore } from "../state/useBrainStore";
import { useVitalsStore } from "../state/useVitalsStore";
import { useWaypathStore } from "../state/useWaypathStore";

const ok = (coords: number[][]) => ({
  json: async () => ({ code: "Ok", routes: [{ geometry: { coordinates: coords } }] }),
});

describe("fetchRoute (OSRM)", () => {
  it("parses geojson [lng,lat] into {lat,lng} and builds the right URL", async () => {
    const f = jest.fn().mockResolvedValue(ok([[10, 50], [10.1, 50.1]]));
    const r = await fetchRoute({ lat: 50, lng: 10 }, { lat: 50.1, lng: 10.1 },
                               { fetchImpl: f as never, baseUrl: "http://osrm.local:5000" });
    expect(r).toEqual([{ lat: 50, lng: 10 }, { lat: 50.1, lng: 10.1 }]);
    expect(f.mock.calls[0][0]).toContain("/route/v1/foot/10,50;10.1,50.1");
  });

  it("returns [] on a non-Ok response", async () => {
    const f = jest.fn().mockResolvedValue({ json: async () => ({ code: "NoRoute" }) });
    expect(await fetchRoute({ lat: 0, lng: 0 }, { lat: 1, lng: 1 },
                            { fetchImpl: f as never, baseUrl: "http://osrm.local:5000" })).toEqual([]);
  });

  it("honors a self-hosted baseUrl", async () => {
    const f = jest.fn().mockResolvedValue(ok([[0, 0]]));
    await fetchRoute({ lat: 0, lng: 0 }, { lat: 0, lng: 0 }, { fetchImpl: f as never, baseUrl: "http://osrm.local:5000" });
    expect(f.mock.calls[0][0]).toContain("http://osrm.local:5000/route/v1/");
  });
});

describe("useWaypathStore", () => {
  // A routing server is somebody else's computer, so there is deliberately NO
  // default — the store starts empty and `navigateTo` refuses until the wearer
  // names one. These tests configure a fake host explicitly, the way the screen
  // does, rather than relying on a default that used to be a public third party.
  const SELF_HOSTED = "http://osrm.local:5000";
  beforeEach(() => {
    useWaypathStore.getState().clear();
    useWaypathStore.getState().setBaseUrl(SELF_HOSTED);
    useBrainStore.setState({ capturePaused: false, incognito: false, cloud: true });
    useVitalsStore.setState({ veiled: false });
  });

  it("routes, then computes the dot on a GPS tick", async () => {
    const f = jest.fn().mockResolvedValue(ok([[0, 0], [0, 0.02]])); // waypoint ~2.2km north
    await useWaypathStore.getState().navigateTo({ lat: 0, lng: 0 }, { lat: 0.02, lng: 0 }, { fetchImpl: f as never });
    expect(useWaypathStore.getState().status).toBe("navigating");
    expect(useWaypathStore.getState().route).toHaveLength(2);

    useWaypathStore.getState().update({ lat: 0, lng: 0 }, 0); // at start, facing north
    const dot = useWaypathStore.getState().dot!;
    expect(dot.arrived).toBe(false);
    expect(Math.abs(dot.angle)).toBeLessThan(5); // waypoint is dead ahead
    expect(dot.distanceM).toBeGreaterThan(1000);
  });

  it("marks arrived at the destination", async () => {
    const f = jest.fn().mockResolvedValue(ok([[0, 0]])); // single waypoint at origin
    await useWaypathStore.getState().navigateTo({ lat: 0, lng: 0 }, { lat: 0, lng: 0 }, { fetchImpl: f as never });
    useWaypathStore.getState().update({ lat: 0, lng: 0 }, 0);
    expect(useWaypathStore.getState().status).toBe("arrived");
  });

  it("errors when no route is found", async () => {
    const f = jest.fn().mockResolvedValue({ json: async () => ({ code: "Ok", routes: [] }) });
    await useWaypathStore.getState().navigateTo({ lat: 0, lng: 0 }, { lat: 1, lng: 1 }, { fetchImpl: f as never });
    expect(useWaypathStore.getState().status).toBe("error");
  });
});

describe("routing never leaks the wearer's location by default", () => {
  beforeEach(() => {
    useWaypathStore.setState({ baseUrl: "" });
    useWaypathStore.getState().clear();
    useBrainStore.setState({ capturePaused: false, incognito: false, cloud: true });
    useVitalsStore.setState({ veiled: false });
  });

  it("ships with no routing server configured", () => {
    expect(useWaypathStore.getState().baseUrl).toBe("");
  });

  it("makes no request at all until the wearer names a server", async () => {
    const f = jest.fn();
    await useWaypathStore.getState().navigateTo(
      { lat: 37.42199, lng: -122.08405 }, { lat: 37.33182, lng: -122.03118 },
      { fetchImpl: f as never });
    expect(f).not.toHaveBeenCalled();
    expect(useWaypathStore.getState().status).toBe("error");
    expect(useWaypathStore.getState().route).toEqual([]);
  });

  it("never falls back to the public demo server", async () => {
    const f = jest.fn().mockResolvedValue(ok([[0, 0]]));
    await fetchRoute({ lat: 1, lng: 2 }, { lat: 3, lng: 4 }, { fetchImpl: f as never });
    expect(f).not.toHaveBeenCalled();
    // the constant still exists for someone who pastes it in on purpose
    expect(OSRM_DEMO).toContain("router.project-osrm.org");
  });

  it("refuses to route while Incognito is on", async () => {
    useWaypathStore.getState().setBaseUrl("http://osrm.local:5000");
    useBrainStore.setState({ capturePaused: true });
    const f = jest.fn();
    await useWaypathStore.getState().navigateTo(
      { lat: 51.5, lng: -0.12 }, { lat: 51.51, lng: -0.13 }, { fetchImpl: f as never });
    expect(f).not.toHaveBeenCalled();
    expect(useWaypathStore.getState().error).toMatch(/Incognito/i);
  });

  it("refuses to route while the glasses have raised the Veil", async () => {
    useWaypathStore.getState().setBaseUrl("http://osrm.local:5000");
    useVitalsStore.setState({ veiled: true });
    const f = jest.fn();
    await useWaypathStore.getState().navigateTo(
      { lat: 51.5, lng: -0.12 }, { lat: 51.51, lng: -0.13 }, { fetchImpl: f as never });
    expect(f).not.toHaveBeenCalled();
  });

  it("refuses to route with the network switch off", async () => {
    useWaypathStore.getState().setBaseUrl("http://osrm.local:5000");
    useBrainStore.setState({ cloud: false });
    const f = jest.fn();
    await useWaypathStore.getState().navigateTo(
      { lat: 51.5, lng: -0.12 }, { lat: 51.51, lng: -0.13 }, { fetchImpl: f as never });
    expect(f).not.toHaveBeenCalled();
  });
});
