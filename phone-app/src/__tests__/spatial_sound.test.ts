/**
 * The phone half of the audible memory palace: a card's `spatial` payload
 * (computed host-side by hud/spatial_audio.py) maps to safe player levels.
 * The mapping is pure and clamped — a malformed payload can never mute the
 * cue or blast the user.
 */
import { spatialLevels } from "../services/spatial";

describe("spatialLevels", () => {
  it("passes through a well-formed payload", () => {
    expect(spatialLevels({ pan: 0.5, gain: 0.8 })).toEqual({
      volume: 0.8,
      pan: 0.5,
    });
  });

  it("keeps a far cue audible (the host MIN_GAIN floor)", () => {
    expect(spatialLevels({ gain: 0.01 }).volume).toBeCloseTo(0.15);
    expect(spatialLevels({ gain: 0 }).volume).toBeCloseTo(0.15);
  });

  it("clamps blast and hard pan", () => {
    expect(spatialLevels({ gain: 9 }).volume).toBe(1);
    expect(spatialLevels({ pan: -7 }).pan).toBe(-1);
    expect(spatialLevels({ pan: 7 }).pan).toBe(1);
  });

  it("defaults centered/full for a missing or malformed payload", () => {
    expect(spatialLevels({})).toEqual({ volume: 1, pan: 0 });
    expect(spatialLevels({ pan: NaN, gain: NaN })).toEqual({ volume: 1, pan: 0 });
    expect(
      spatialLevels({ pan: "x" as unknown as number, gain: undefined }),
    ).toEqual({ volume: 1, pan: 0 });
  });
});
