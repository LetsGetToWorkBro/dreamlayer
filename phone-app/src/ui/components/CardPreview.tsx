// CardPreview.tsx
// On-phone renderer that shows *exactly* what the glasses will draw.
//
// Halo Cinema v1 QA truth (docs/HALO_CINEMA_V1.md Phase 5): this component
// mirrors halo-lua/display/renderer.lua card layouts 1:1, using the same
// palette tokens (theme/colors.ts haloPalette) and the same geometry
// constants. If the phone preview and the glasses diverge, one of them is
// wrong — fix the divergent side, never fork the design.
//
// Dependency note: react-native-svg (PROPOSED_DEPENDENCY in
// docs/HALO_CINEMA_V1.md) — frame.display parity needs arcs/beziers that
// RN core Views cannot draw.
import React from "react";
import { View } from "react-native";
import Svg, { Circle, G, Line, Path, Polygon, Rect, Text as SvgText } from "react-native-svg";
import { haloPalette as P } from "../theme/colors";

const SIZE = 256;
const CX = 128;
const CY = 128;

export interface HaloCard {
  type: string;
  primary?: string;
  eyebrow?: string;
  detail?: string;
  footer?: string;
  place?: string;
  object?: string;
  person?: string;
  headline?: string;
  why?: string;
  due?: string;
  verdict?: string;
  confidence?: number;
  has_avatar?: boolean;
  version?: number;
  dominant_color?: number;
  shapes?: { kind: string; x: number; y: number; size: number }[];
  stages?: { name: string; confidence: number; direction: string }[];
}

function confColor(c?: number): string {
  if (c == null) return P.textGhost;
  if (c >= 0.75) return P.confidenceHigh;
  if (c >= 0.4) return P.confidenceMed;
  return P.confidenceLow;
}

/** SVG arc path, angles in degrees, 12 o'clock = -90. */
function arcPath(cx: number, cy: number, r: number, a0: number, a1: number): string {
  const rad = (d: number) => (d * Math.PI) / 180;
  const x0 = cx + r * Math.cos(rad(a0));
  const y0 = cy + r * Math.sin(rad(a0));
  const x1 = cx + r * Math.cos(rad(a1));
  const y1 = cy + r * Math.sin(rad(a1));
  const large = Math.abs(a1 - a0) > 180 ? 1 : 0;
  return `M ${x0} ${y0} A ${r} ${r} 0 ${large} 1 ${x1} ${y1}`;
}

const Eyebrow = ({ y, children, color = P.memoryTrace }: any) => (
  <SvgText x={CX} y={y} fill={color} fontSize={10} letterSpacing={2}
           textAnchor="middle">{children}</SvgText>
);

// ---------------------------------------------------------------------------
// Per-card layouts (mirror renderer.lua draw_* functions)
// ---------------------------------------------------------------------------

function ObjectRecall({ card }: { card: HaloCard }) {
  const jcol = confColor(card.confidence);
  return (
    <G>
      <Line x1={44} y1={72} x2={44} y2={188} stroke={P.memoryTrace} strokeWidth={2} />
      <Circle cx={44} cy={72} r={3} fill={P.memoryTrace} />
      <Circle cx={44} cy={188} r={3} fill={jcol} />
      <SvgText x={54} y={84} fill={P.memoryTrace} fontSize={10}>
        {(card.object || card.primary || "").toUpperCase()}
      </SvgText>
      <Path d="M 46 90 Q 200 62 155 150" stroke={P.memoryTrace} strokeWidth={2}
            fill="none" strokeDasharray="7 5" />
      <SvgText x={155} y={154} fill={P.textPrimary} fontSize={22}
               textAnchor="middle">{card.place || ""}</SvgText>
      {card.detail ? (
        <SvgText x={CX} y={181} fill={P.textSecondary} fontSize={9}
                 textAnchor="middle">[ {card.detail} ]</SvgText>
      ) : null}
      <SvgText x={CX} y={201} fill={P.textGhost} fontSize={9}
               textAnchor="middle">{card.footer || ""}</SvgText>
    </G>
  );
}

function CommitmentRecall({ card }: { card: HaloCard }) {
  return (
    <G>
      <Eyebrow y={71}>YOU PROMISED {(card.person || "").toUpperCase()}</Eyebrow>
      {[84, 108, 132].map((y, i) => (
        <Rect key={y} x={CX - 64} y={y} width={128} height={18} rx={4}
              stroke={i === 2 ? P.memoryTrace : P.borderSubtle} fill="none" />
      ))}
      <SvgText x={CX} y={121} fill={P.textPrimary} fontSize={12}
               textAnchor="middle">{card.primary || ""}</SvgText>
      <SvgText x={CX} y={145} fill={P.memoryTrace} fontSize={11}
               textAnchor="middle">{card.due || card.footer || ""}</SvgText>
      <Circle cx={CX} cy={168} r={2.5} fill={confColor(card.confidence)} />
    </G>
  );
}

function PersonContext({ card }: { card: HaloCard }) {
  const sweep = (card.confidence ?? 1) * 359.9;
  return (
    <G>
      {card.has_avatar && (
        <G>
          {[18, 23, 28].map((r, i) => (
            <Path key={r} d={arcPath(CX, 52, r, -90, -90 + sweep)}
                  stroke={P.accentMemory} strokeOpacity={1 - i * 0.25}
                  strokeWidth={1} fill="none" />
          ))}
          <Circle cx={CX} cy={52} r={15} stroke={P.borderSubtle} fill="none" />
          <SvgText x={CX} y={57} fill={P.textPrimary} fontSize={13}
                   textAnchor="middle">{(card.primary || "?")[0]}</SvgText>
        </G>
      )}
      <SvgText x={CX} y={104} fill={P.memoryTrace} fontSize={17}
               textAnchor="middle">{card.primary || ""}</SvgText>
      <Line x1={72} y1={116} x2={184} y2={116} stroke={P.borderSubtle} />
      <SvgText x={CX} y={144} fill={P.textPrimary} fontSize={12}
               textAnchor="middle">{card.why || card.headline || ""}</SvgText>
      <SvgText x={CX} y={168} fill={P.textSecondary} fontSize={10}
               textAnchor="middle">{card.detail || ""}</SvgText>
      {card.confidence != null && (
        <Circle cx={CX} cy={186} r={3} fill={confColor(card.confidence)} />
      )}
    </G>
  );
}

const GAUGE_DIR: Record<string, string> = {
  truthful: P.accentSuccess,
  deceptive: P.accentAttention,
  insufficient: P.textGhost,
};

function TruthGauge({ card }: { card: HaloCard }) {
  const stages = card.stages || [];
  return (
    <G>
      <Eyebrow y={49} color={P.textGhost}>TRUTH LENS</Eyebrow>
      {Array.from({ length: 9 }).map((_, i) => {
        const r = 20 + i * 4;
        const s = stages[i];
        const sweep = Math.min(1, Math.max(0, s?.confidence ?? 0)) * 359.9;
        return (
          <G key={i}>
            <Circle cx={CX} cy={CY} r={r} stroke={P.borderSubtle}
                    strokeOpacity={0.35} fill="none" />
            {sweep > 4 && (
              <Path d={arcPath(CX, CY, r, -90, -90 + sweep)}
                    stroke={GAUGE_DIR[s?.direction ?? "insufficient"]}
                    strokeWidth={2} fill="none" />
            )}
          </G>
        );
      })}
      <SvgText x={CX} y={CY - 2} fill={P.textPrimary} fontSize={13}
               textAnchor="middle">{card.verdict || card.primary || ""}</SvgText>
      {card.confidence != null && (
        <Circle cx={CX} cy={CY + 14} r={3} fill={confColor(card.confidence)} />
      )}
      <SvgText x={CX} y={212} fill={P.textGhost} fontSize={9}
               textAnchor="middle">{card.footer || ""}</SvgText>
    </G>
  );
}

function PrivacyPaused() {
  const hex = Array.from({ length: 6 }, (_, i) => {
    const a = ((60 * i - 30) * Math.PI) / 180;
    return `${CX + 26 * Math.cos(a)},${CY - 14 + 26 * Math.sin(a)}`;
  }).join(" ");
  return (
    <G>
      <Circle cx={CX} cy={CY} r={108} stroke={P.privacyDanger}
              strokeOpacity={0.15} fill="none" />
      <Circle cx={CX} cy={CY} r={88} stroke={P.privacyDanger}
              strokeOpacity={0.08} fill="none" />
      <Polygon points={hex} stroke={P.privacyDanger} strokeWidth={2} fill="none" />
      <Rect x={CX - 7} y={CY - 26} width={4} height={24} fill={P.privacyDanger} />
      <Rect x={CX + 3} y={CY - 26} width={4} height={24} fill={P.privacyDanger} />
      <SvgText x={CX} y={CY + 36} fill={P.privacyCaution} fontSize={11}
               textAnchor="middle">PAUSED</SvgText>
      <SvgText x={CX} y={CY + 52} fill={P.textGhost} fontSize={9}
               textAnchor="middle">Nothing is captured</SvgText>
    </G>
  );
}

function WorldAnchor({ card }: { card: HaloCard }) {
  return (
    <G opacity={0.7}>
      <SvgText x={CX} y={199} fill={P.textGhost} fontSize={9}
               textAnchor="middle">• MEMORY ECHO •</SvgText>
      <SvgText x={CX} y={217} fill={P.textGhost} fontSize={10}
               textAnchor="middle">{card.primary || ""}</SvgText>
      <SvgText x={CX} y={233} fill={P.textGhost} fontSize={9}
               textAnchor="middle">{card.detail || ""}</SvgText>
    </G>
  );
}

function SynesthesiaV2({ card }: { card: HaloCard }) {
  const dom = card.dominant_color != null
    ? `#${card.dominant_color.toString(16).padStart(6, "0")}`
    : P.accentMemory;
  return (
    <G>
      <SvgText x={CX} y={67} fill={P.textGhost} fontSize={9} letterSpacing={3}
               textAnchor="middle">DREAM</SvgText>
      <SvgText x={CX} y={100} fill={P.textPrimary} fontSize={12}
               textAnchor="middle">{card.primary || ""}</SvgText>
      <Line x1={48} y1={126} x2={208} y2={126} stroke={P.borderSubtle} />
      {(card.shapes || []).slice(0, 3).map((s, i) => {
        const x = 64 + s.x;
        const y = 128 + s.y * 0.75;
        const half = s.size / 2;
        if (s.kind === "line")
          return <Line key={i} x1={x - half} y1={y} x2={x + half} y2={y}
                       stroke={dom} strokeWidth={2} />;
        if (s.kind === "rect")
          return <Rect key={i} x={x - half} y={y - half / 2} width={s.size}
                       height={half} stroke={dom} strokeWidth={2} fill="none" />;
        if (s.kind === "triangle")
          return <Polygon key={i}
                          points={`${x},${y - half} ${x + half},${y + half} ${x - half},${y + half}`}
                          stroke={dom} fill="none" />;
        return <Circle key={i} cx={x} cy={y} r={half} stroke={dom}
                       strokeWidth={2} fill="none" />;
      })}
    </G>
  );
}

function Fallback({ card }: { card: HaloCard }) {
  return (
    <G>
      <SvgText x={CX} y={CY - 6} fill={P.textPrimary} fontSize={13}
               textAnchor="middle">{card.primary || card.type}</SvgText>
      <SvgText x={CX} y={CY + 18} fill={P.textSecondary} fontSize={10}
               textAnchor="middle">{card.detail || ""}</SvgText>
    </G>
  );
}

const DISPATCH: Record<string, React.ComponentType<{ card: HaloCard }>> = {
  ObjectRecallCard: ObjectRecall,
  CommitmentRecallCard: CommitmentRecall,
  PersonContextCard: PersonContext,
  TruthLensCard: TruthGauge,
  PrivacyPausedCard: PrivacyPaused as any,
  WorldAnchorCard: WorldAnchor,
  SynesthesiaCard: SynesthesiaV2,
};

export function CardPreview({ card, size = 256 }: { card: HaloCard; size?: number }) {
  const Body = DISPATCH[card.type] ?? Fallback;
  return (
    <View style={{ width: size, height: size, borderRadius: size / 2, overflow: "hidden" }}>
      <Svg width={size} height={size} viewBox={`0 0 ${SIZE} ${SIZE}`}>
        <Circle cx={CX} cy={CY} r={127} fill={P.background}
                stroke={P.borderSubtle} strokeWidth={1} />
        <Body card={card} />
      </Svg>
    </View>
  );
}

export default CardPreview;
