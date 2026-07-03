// HorizonPreview.tsx
// The Meridian day-ring, mirrored on the phone (docs/cinema_v2/horizon.md,
// horizon_frame.md). Same QA-truth doctrine as CardPreview: this renders
// exactly what halo-lua/display/horizon.lua plots from {t:"horizon"}
// frames — if phone and glasses diverge, one of them is wrong; fix the
// divergent side, never fork.
//
// Geometry constants come from theme/motion.ts `meridian` (parity with
// halo-lua/display/animations.lua MER_*). Colors from haloPalette only.

import React, { useEffect, useState } from "react";
import Svg, { Circle, G, Path } from "react-native-svg";
import { haloPalette as P } from "../theme/colors";
import { meridian as M } from "../theme/motion";

const SIZE = 256;
const CX = SIZE / 2;
const CY = SIZE / 2;

export interface HorizonMark {
  /** screen-space angle, degrees (now = -90, past clockwise) */
  deg: number;
  kind: "memory" | "promise" | "person" | "elder" | "future_cap";
  /** promise drift state 1..5 (blooming..shattered); memories 0 */
  state?: number;
  /** luma tier 0 floor / 1 dim / 2 full */
  luma?: number;
}

export interface HorizonState {
  marks: HorizonMark[];
  paused?: boolean;
  /** dream light: memory marks drop to floor tier */
  dim?: boolean;
}

function polar(r: number, deg: number): [number, number] {
  const rad = (deg * Math.PI) / 180;
  return [CX + r * Math.cos(rad), CY + r * Math.sin(rad)];
}

function arcPath(r: number, a0: number, a1: number): string {
  const [x0, y0] = polar(r, a0);
  const [x1, y1] = polar(r, a1);
  const large = Math.abs(a1 - a0) > 180 ? 1 : 0;
  return `M ${x0} ${y0} A ${r} ${r} 0 ${large} 1 ${x1} ${y1}`;
}

function tickPath(deg: number, r0: number, r1: number): string {
  const [x0, y0] = polar(r0, deg);
  const [x1, y1] = polar(r1, deg);
  return `M ${x0} ${y0} L ${x1} ${y1}`;
}

const MEM_COLOR = [P.borderSubtle, P.accentMemoryDim, P.accentMemory] as const;

function Mark({ mk, dim }: { mk: HorizonMark; dim?: boolean }) {
  if (mk.kind === "elder") {
    return <Path d={tickPath(M.elderDeg, M.markBaseR, M.markBaseR + 4)}
                 stroke={P.textGhost} strokeWidth={1} />;
  }
  if (mk.kind === "future_cap") {
    const [x, y] = polar(M.promiseR, M.futureCapDeg);
    return <Circle cx={x} cy={y} r={2} fill={P.textGhost} />;
  }
  if (mk.kind === "promise") {
    // promises never dim — they don't sleep
    const state = mk.state ?? 2;
    const slipped = state >= 4;
    const r = slipped ? M.promiseSlipR : M.promiseR;
    if (state === 5) {
      // shattered: the fractured tick — two segments, a 3px gap
      return (
        <G>
          <Path d={tickPath(mk.deg, r - 7, r - 2)} stroke={P.statusPaused} strokeWidth={2} />
          <Path d={tickPath(mk.deg, r + 1, r + 6)} stroke={P.statusPaused} strokeWidth={2} />
        </G>
      );
    }
    const color = state >= 3 ? P.warningAmber : P.confidenceLow;
    const dot = state === 1 ? 2 : 3;
    const [x, y] = polar(r, mk.deg);
    return (
      <G>
        <Circle cx={x} cy={y} r={dot} fill={color} />
        {state === 3 && (
          <Path d={tickPath(mk.deg, r - 6, r - 3)} stroke={color} strokeWidth={1} />
        )}
      </G>
    );
  }
  const luma = dim ? 0 : Math.max(0, Math.min(2, mk.luma ?? 1));
  if (mk.kind === "person") {
    const color = luma >= 2 ? P.accentMemory : luma >= 1 ? P.accentMemoryDim : P.borderSubtle;
    const [px, py] = polar(110, mk.deg);
    return (
      <G>
        <Path d={tickPath(mk.deg, M.markBaseR, M.markBaseR + 5)}
              stroke={color} strokeWidth={1} />
        <Circle cx={px} cy={py} r={2} stroke={color} fill="none" />
      </G>
    );
  }
  return <Path d={tickPath(mk.deg, M.markBaseR, M.markBaseR + (M.markLen[luma] ?? 0))}
               stroke={MEM_COLOR[luma]} strokeWidth={1} />;
}

export function HorizonPreview({
  state,
  /** breathing notch phase source; omit for a static preview */
  animateNotch = true,
}: {
  state: HorizonState;
  animateNotch?: boolean;
}) {
  const [notchLen, setNotchLen] = useState((M.nowLenMin + M.nowLenMax) / 2);

  useEffect(() => {
    if (!animateNotch) return;
    const t0 = Date.now();
    const id = setInterval(() => {
      const phase = ((Date.now() - t0) % 3200) / 3200;
      const breathe = (Math.sin(phase * 2 * Math.PI) + 1) / 2;
      setNotchLen(M.nowLenMin + (M.nowLenMax - M.nowLenMin) * breathe);
    }, 100);
    return () => clearInterval(id);
  }, [animateNotch]);

  const marks = state.paused ? [] : state.marks;
  return (
    <Svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`}>
      <Circle cx={CX} cy={CY} r={127} fill={P.background}
              stroke={P.borderSubtle} strokeWidth={1} />
      {/* the rim track: its absence at the bottom is the seam */}
      <Path d={arcPath(M.trackR, M.seamToDeg, 360 + M.seamFromDeg)}
            stroke={P.borderSubtle} strokeWidth={1} fill="none" />
      {marks.map((mk, i) => (
        <Mark key={i} mk={mk} dim={state.dim} />
      ))}
      {/* the now-notch: the only mark that crosses the track */}
      <Path d={tickPath(M.nowDeg, 96, 96 + notchLen)}
            stroke={state.paused ? P.statusPaused : P.accentMemory}
            strokeWidth={2} />
    </Svg>
  );
}

/** Deterministic mock day for offline dev (same pattern as DreamCanvas). */
export function mockHorizonState(): HorizonState {
  return {
    marks: [
      { deg: -90 + 135, kind: "memory", luma: 1 },
      { deg: -90 + 128, kind: "memory", luma: 1 },
      { deg: -90 + 100, kind: "memory", luma: 1 },
      { deg: -90 + 84, kind: "person", luma: 2 },
      { deg: -90 + 60, kind: "memory", luma: 2 },
      { deg: -90 + 20, kind: "memory", luma: 2 },
      { deg: -90 + 4, kind: "memory", luma: 2 },
      { deg: -90 - 45, kind: "promise", state: 2 },
      { deg: -90 - 120, kind: "promise", state: 1 },
      { deg: 0, kind: "elder" },
    ],
  };
}

export default HorizonPreview;
