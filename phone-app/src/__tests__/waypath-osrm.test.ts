/** OSRM routing adapter + the Waypath store (4.7). Fetch is injected — no live
 * network, no maps SDK. */
import { fetchRoute } from "../nav/osrm";
import { useWaypathStore } from "../state/useWaypathStore";

const ok = (coords: number[][]) => ({
  json: async () => ({ code: "Ok", routes: [{ geometry: { coordinates: coords } }] }),
});

describe("fetchRoute (OSRM)", () => {
  it("parses geojson [lng,lat] into {lat,lng} and builds the right URL", async () => {
    const f = jest.fn().mockResolvedValue(ok([[10, 50], [10.1, 50.1]]));
    const r = await fetchRoute({ lat: 50, lng: 10 }, { lat: 50.1, lng: 10.1 }, { fetchImpl: f as never });
    expect(r).toEqual([{ lat: 50, lng: 10 }, { lat: 50.1, lng: 10.1 }]);
    expect(f.mock.calls[0][0]).toContain("/route/v1/foot/10,50;10.1,50.1");
  });

  it("returns [] on a non-Ok response", async () => {
    const f = jest.fn().mockResolvedValue({ json: async () => ({ code: "NoRoute" }) });
    expect(await fetchRoute({ lat: 0, lng: 0 }, { lat: 1, lng: 1 }, { fetchImpl: f as never })).toEqual([]);
  });

  it("honors a self-hosted baseUrl", async () => {
    const f = jest.fn().mockResolvedValue(ok([[0, 0]]));
    await fetchRoute({ lat: 0, lng: 0 }, { lat: 0, lng: 0 }, { fetchImpl: f as never, baseUrl: "http://osrm.local:5000" });
    expect(f.mock.calls[0][0]).toContain("http://osrm.local:5000/route/v1/");
  });
});

describe("useWaypathStore", () => {
  beforeEach(() => useWaypathStore.getState().clear());

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
