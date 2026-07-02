// DreamCanvas.tsx
// Live preview of Dream Mode's palette weather + Line Field 2.0 — a *scope*
// into the glasses' ambient state.
//
// Tick source: pass a WebSocket-backed source in production
// (useDreamTicks(ws)) or nothing to get the built-in mock that replays the
// same two-band weather model as host-python mic_reactor.py and the same
// curl-noise field as imu_reactor.py — value-noise lattice included, so
// the phone swirls exactly like the glasses.
import React, { useEffect, useRef, useState } from "react";
import { View } from "react-native";
import Svg, { Circle, Line, Rect } from "react-native-svg";
import { haloPalette as P } from "../theme/colors";
import { signatures } from "../theme/motion";

const SIZE = 256;
const CX = 128;
const CY = 128;
const N_VECTORS = 12;
const RING_R = 78;
const TICK_MS = 500; // 2 Hz, same as DreamEngine.AMBIENT_HZ

export interface DreamTick {
  /** sky/energy slot colors as #RRGGBB (already YCbCr→RGB converted) */
  sky: string;
  energy: string;
  /** 12 line-field vectors, [x1,y1,x2,y2] each */
  field: [number, number, number, number][];
  amplitude: number; // 0-1, drives particle brightness
}

// ---------------------------------------------------------------------------
// Mock tick source — same math as imu_reactor.py / mic_reactor.py
// ---------------------------------------------------------------------------

/** Value noise on the shared 289-lattice (lib/easing.lua perlin1d). */
function vnoise(x: number): number {
  const h = (n: number) => {
    n = ((Math.floor(n) % 289) + 289) % 289;
    return ((n * 34 + 1) * n % 289) / 144.5 - 1.0;
  };
  const x0 = Math.floor(x);
  const f = x - x0;
  const u = f * f * (3 - 2 * f);
  return h(x0) + (h(x0 + 1) - h(x0)) * u;
}

function mockTick(t: number): DreamTick {
  // Simulated room: slow pressure swell + occasional energy
  const pressure = 0.5 + 0.5 * vnoise(t * 0.11);
  const energy = Math.max(0, vnoise(t * 0.31 + 40));
  const amplitude = 0.3 + 0.4 * pressure + 0.3 * energy;

  // Two-band weather → approximate RGB (mirrors sky Cb / energy Cr axes)
  const skyBlue = Math.round(154 + pressure * 80);
  const sky = `rgb(${Math.round(44 - pressure * 20)}, ${Math.round(
    199 - pressure * 60)}, ${skyBlue})`;
  const emberRed = Math.round(120 + energy * 120);
  const eng = `rgb(${emberRed}, ${Math.round(120 - energy * 30)}, 82)`;

  // Curl-noise field, phase rotates with a damped drift
  const phase = t * 0.05;
  const field: [number, number, number, number][] = [];
  for (let i = 0; i < N_VECTORS; i++) {
    const a = phase + (i * 2 * Math.PI) / N_VECTORS;
    const ax = CX + RING_R * Math.cos(a);
    const ay = CY + RING_R * Math.sin(a);
    const n = vnoise(i * 3.7 + phase * 2.1);
    const dn = vnoise(i * 3.7 + phase * 2.1 + 0.5) - n;
    const ca = a + Math.PI / 2 + dn * 1.8;
    const ln = 14 + (n * 0.5 + 0.5) * 20;
    field.push([
      ax - ln * Math.cos(ca), ay - ln * Math.sin(ca),
      ax + ln * Math.cos(ca), ay + ln * Math.sin(ca),
    ]);
  }
  return { sky, energy: eng, field, amplitude };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function DreamCanvas({
  source,
  size = 256,
}: {
  /** external tick source (e.g. WebSocket): subscribe(cb) → unsubscribe */
  source?: (cb: (tick: DreamTick) => void) => () => void;
  size?: number;
}) {
  const [tick, setTick] = useState<DreamTick>(() => mockTick(0));
  const t = useRef(0);

  useEffect(() => {
    if (source) return source(setTick);
    const id = setInterval(() => {
      t.current += TICK_MS / 1000;
      setTick(mockTick(t.current));
    }, TICK_MS);
    return () => clearInterval(id);
  }, [source]);

  const halo = signatures.confidenceHalo;
  return (
    <View style={{ width: size, height: size, borderRadius: size / 2, overflow: "hidden" }}>
      <Svg width={size} height={size} viewBox={`0 0 ${SIZE} ${SIZE}`}>
        <Circle cx={CX} cy={CY} r={127} fill={P.background}
                stroke={P.borderSubtle} strokeWidth={1} />
        {/* sky wash: dithered look via low-opacity ring bands */}
        {[110, 92, 74].map((r, i) => (
          <Circle key={r} cx={CX} cy={CY} r={r} stroke={tick.sky}
                  strokeOpacity={0.10 + i * 0.04} strokeWidth={10} fill="none" />
        ))}
        {/* Line Field 2.0 */}
        {tick.field.map(([x1, y1, x2, y2], i) => (
          <Line key={i} x1={x1} y1={y1} x2={x2} y2={y2}
                stroke={i % 3 === 0 ? tick.energy : tick.sky}
                strokeOpacity={0.35 + tick.amplitude * 0.4} />
        ))}
        {/* energy core: breathes with amplitude on the halo period */}
        <Circle cx={CX} cy={CY} r={halo.rBase * (0.6 + tick.amplitude * 0.5)}
                stroke={tick.energy} strokeOpacity={0.6} fill="none" />
        <Circle cx={CX} cy={CY} r={3} fill={tick.energy} />
        {/* pressure gauge tick at 12 o'clock */}
        <Rect x={CX - 1} y={10} width={2} height={8} fill={tick.sky} />
      </Svg>
    </View>
  );
}

export default DreamCanvas;
