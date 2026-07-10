/** Waypath Lens geometry (4.7): bearing/distance/relative-angle + the dot the
 * lens sends to the glasses. Pure math — GPS and the routing API are injected. */
import { bearing, dotFor, haversine, nextWaypointIndex, relativeAngle } from "../nav/waypath";

const ORIGIN = { lat: 0, lng: 0 };

describe("bearing", () => {
  it("points north/east/south/west", () => {
    expect(Math.round(bearing(ORIGIN, { lat: 1, lng: 0 }))).toBe(0); // due north
    expect(Math.round(bearing(ORIGIN, { lat: 0, lng: 1 }))).toBe(90); // due east
    expect(Math.round(bearing(ORIGIN, { lat: -1, lng: 0 }))).toBe(180); // south
    expect(Math.round(bearing(ORIGIN, { lat: 0, lng: -1 }))).toBe(270); // west
  });
});

describe("haversine", () => {
  it("measures ~111 km per degree of latitude", () => {
    const d = haversine(ORIGIN, { lat: 1, lng: 0 });
    expect(d).toBeGreaterThan(110_000);
    expect(d).toBeLessThan(112_000);
  });
});

describe("relativeAngle", () => {
  it("is 0 dead ahead and wraps to (-180,180]", () => {
    expect(relativeAngle(90, 90)).toBe(0);
    expect(relativeAngle(90, 0)).toBe(90); // target east, facing north → hard right
    expect(relativeAngle(0, 90)).toBe(-90); // target north, facing east → hard left
    expect(relativeAngle(10, 350)).toBe(20); // wraps across north
  });
});

describe("nextWaypointIndex", () => {
  const route = [
    { lat: 0, lng: 0 },
    { lat: 0.01, lng: 0 },
    { lat: 0.02, lng: 0 },
  ];
  it("skips waypoints already reached", () => {
    // standing on waypoint 0 → next is 1
    expect(nextWaypointIndex({ lat: 0, lng: 0 }, route)).toBe(1);
  });
  it("returns route.length when arrived", () => {
    expect(nextWaypointIndex({ lat: 0.02, lng: 0 }, route)).toBe(route.length);
  });
});

describe("dotFor", () => {
  const route = [{ lat: 0.01, lng: 0 }]; // a single waypoint due north

  it("returns the dot angle + distance to the next waypoint", () => {
    const dot = dotFor({ lat: 0, lng: 0 }, 0, route)!; // facing north
    expect(dot.arrived).toBe(false);
    expect(dot.angle).toBe(0); // waypoint is dead ahead
    expect(dot.distanceM).toBeGreaterThan(1000);
  });

  it("puts the dot to the side when you turn your head", () => {
    const dot = dotFor({ lat: 0, lng: 0 }, 90, route)!; // facing east, waypoint north
    expect(dot.angle).toBe(-90); // hard left
  });

  it("reports arrived at the final waypoint", () => {
    const dot = dotFor({ lat: 0.01, lng: 0 }, 0, route)!;
    expect(dot.arrived).toBe(true);
  });

  it("returns null with no route", () => {
    expect(dotFor(ORIGIN, 0, [])).toBeNull();
  });
});
