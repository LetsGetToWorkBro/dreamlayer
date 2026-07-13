/**
 * spatial.ts — the pure half of the audible memory palace on the phone.
 *
 * A HUD card can carry a `spatial` payload (computed host-side by
 * hud/spatial_audio.py from a Waypath cue's bearing + distance). This maps it
 * to safe player levels: volume from the distance gain, stereo pan from the
 * azimuth. Pure + clamped so a malformed payload can never mute the cue or
 * blast the user; kept free of asset requires so the logic tests load it.
 */

export type SpatialCue = { pan?: number; gain?: number; behind?: boolean };

export function spatialLevels(cue: SpatialCue): { volume: number; pan: number } {
  const clamp = (v: number, lo: number, hi: number) =>
    Math.min(hi, Math.max(lo, v));
  const gain = typeof cue.gain === "number" && isFinite(cue.gain) ? cue.gain : 1;
  const pan = typeof cue.pan === "number" && isFinite(cue.pan) ? cue.pan : 0;
  // a far cue stays audible (mirror of the host's MIN_GAIN floor)
  return { volume: clamp(gain, 0.15, 1), pan: clamp(pan, -1, 1) };
}
