import React from "react";
import { View, Text, TextInput, StyleSheet } from "react-native";
import { Screen } from "../src/ui/components/Screen";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { Card, Section } from "../src/ui/components/Card";
import { EmptyState } from "../src/ui/components/EmptyState";
import { Tappable } from "../src/ui/components/Tappable";
import { useTheme, makeThemedStyles } from "../src/ui/theme/useTheme";
import { typography } from "../src/ui/theme/typography";
import { radius, space } from "../src/ui/theme/spacing";
import { useBrainStore } from "../src/state/useBrainStore";
import { useLensStore, ProvenanceResult } from "../src/state/useLensStore";

/**
 * Lenses — the seven that had no phone surface.
 *
 * Provenance, Candor, Commitment Drift, Quests, Stasis, Premonition and Inner
 * Weather ran on the glasses' orchestrator and were unreachable from the
 * shipped Brain, so no screen could have shown them. This is the surface for
 * all seven; `useLensStore` is the client.
 *
 * The one design rule this screen keeps everywhere: NEVER RENDER A VEILED LENS
 * AS A CALM ONE. When the Veil is down every read lens returns null, and "no
 * contradictions found" is a materially different sentence from "the Brain was
 * not allowed to look". Same for an unpaired Brain: an empty list drawn with
 * confidence is the failure this whole surface exists to avoid.
 */

const STATE_TINT: Record<string, "accentSuccess" | "accentMemory" | "accentAttention" | "accentError"> = {
  blooming: "accentSuccess",
  drifting: "accentMemory",
  cracking: "accentAttention",
  shattered: "accentError",
};

function ago(ts: number): string {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 172800) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

export default function Lenses() {
  const s = useS();
  const { colors } = useTheme();
  const connected = useBrainStore((x) => x.macMini.connected);
  const st = useLensStore();

  const [claim, setClaim] = React.useState("");
  const [trace, setTrace] = React.useState<ProvenanceResult | null>(null);
  const [traceVeiled, setTraceVeiled] = React.useState(false);
  const [note, setNote] = React.useState("");

  React.useEffect(() => {
    if (connected) void st.refresh();
    // one refresh per connection change — the lenses are pull, not a feed
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected]);

  const doTrace = async () => {
    const r = await st.trace(claim);
    setTrace(r);
    setTraceVeiled(r === null && claim.trim().length > 0);
  };

  if (!connected) {
    return (
      <Screen>
        <ScreenHeader title="Lenses" eyebrow="Your Brain" />
        <EmptyState
          title="Connect your Mac mini"
          hint="These seven lenses read your own timeline, so they live on your Brain and never leave it."
        />
      </Screen>
    );
  }

  if (st.loaded && !st.reachable) {
    return (
      <Screen>
        <ScreenHeader title="Lenses" eyebrow="Your Brain" />
        <EmptyState title="Couldn’t reach your Brain" hint="Is the Mac mini awake and on the same network?" />
      </Screen>
    );
  }

  return (
    <Screen>
      <ScreenHeader
        title="Lenses"
        eyebrow="Your Brain"
        subtitle={
          st.status
            ? `${st.status.ring} statement${st.status.ring === 1 ? "" : "s"} in the last day · ${st.status.held} held`
            : undefined
        }
      />

      {st.veiled ? (
        <Card accent={colors.accentAttention}>
          <Text style={[typography.eyebrow, { color: colors.accentAttention }]}>THE VEIL IS DOWN</Text>
          <Text style={[typography.body, { color: colors.textPrimary, marginTop: space.sm }]}>
            These lenses read what was said around you, so the shield stops them at the door. Nothing below is
            “all clear” — it is “not looked at”.
          </Text>
        </Card>
      ) : null}

      {/* ---------------------------------------------------------------- */}
      <Section label="Provenance — where did I get this?" first />
      <Card>
        <TextInput
          value={claim}
          onChangeText={setClaim}
          onSubmitEditing={doTrace}
          placeholder="the venue is booked for Friday"
          placeholderTextColor={colors.textSecondary}
          autoCapitalize="none"
          style={s.input}
        />
        <Tappable onPress={doTrace} style={s.button}>
          <Text style={[typography.body, { color: colors.textPrimary }]}>Trace it</Text>
        </Tappable>
        {traceVeiled ? (
          <Text style={[typography.caption, { color: colors.accentAttention, marginTop: space.md }]}>
            The Veil is down — the Brain was not allowed to look. This is not “no source”.
          </Text>
        ) : trace === null ? null : !trace.found ? (
          <Text style={[typography.caption, { color: colors.textSecondary, marginTop: space.md }]}>
            Never heard it. Nothing in the last day bears on this.
          </Text>
        ) : (
          <View style={{ marginTop: space.md }}>
            <Text style={[typography.eyebrow, { color: statusTint(trace.status, colors) }]}>
              {(trace.status ?? "").toUpperCase()}
            </Text>
            <Text style={[typography.body, { color: colors.textPrimary, marginTop: space.xs }]}>
              from {trace.origin?.attribution}
            </Text>
            {trace.corroboration && trace.corroboration >= 2 ? (
              <Text style={[typography.caption, { color: colors.textSecondary }]}>
                {trace.corroboration} attributions
              </Text>
            ) : null}
            {trace.contradiction ? (
              <Text style={[typography.caption, { color: colors.accentError, marginTop: space.xs }]}>
                but also: {trace.contradiction}
              </Text>
            ) : null}
          </View>
        )}
      </Card>

      {/* ---------------------------------------------------------------- */}
      {st.lastCandor?.fired ? (
        <>
          <Section label="Candor — you said different before" />
          <Card accent={colors.accentAttention}>
            <Text style={[typography.body, { color: colors.textPrimary }]}>{st.lastCandor.claim}</Text>
            {/* the FOOTER is the lens: without the prior statement this card
                says nothing at all */}
            <Text style={[typography.caption, { color: colors.textSecondary, marginTop: space.sm }]}>
              earlier: {st.lastCandor.prior}
            </Text>
          </Card>
        </>
      ) : null}

      {/* ---------------------------------------------------------------- */}
      <Section label="Commitments" />
      {st.quests.length === 0 ? (
        <Card>
          <Text style={[typography.caption, { color: colors.textSecondary }]}>
            {st.veiled
              ? "Not looked at — the Veil is down."
              : "Nothing tracked. Promises you make out loud land here on their own."}
          </Text>
        </Card>
      ) : (
        st.quests.map((q) => (
          <Card key={q.subject} accent={colors[STATE_TINT[q.state] ?? "accentMemory"]}>
            <Text style={[typography.body, { color: colors.textPrimary }]}>{q.subject}</Text>
            <Text style={[typography.caption, { color: colors.textSecondary, marginTop: space.xs }]}>
              {q.status} · +{q.reward_xp} XP
            </Text>
            <View style={s.meterTrack}>
              <View style={[s.meterFill, { width: `${Math.round(q.progress * 100)}%`, backgroundColor: colors[STATE_TINT[q.state] ?? "accentMemory"] }]} />
            </View>
            <View style={s.row}>
              <Tappable onPress={() => void st.completeQuest(q.subject)} style={s.button}>
                <Text style={[typography.caption, { color: colors.accentSuccess }]}>Kept it</Text>
              </Tappable>
              <Tappable onPress={() => void st.tend(q.subject)} style={s.button}>
                <Text style={[typography.caption, { color: colors.textPrimary }]}>Tend</Text>
              </Tappable>
              <Tappable onPress={() => void st.abandonQuest(q.subject)} style={s.button}>
                <Text style={[typography.caption, { color: colors.textSecondary }]}>Let go</Text>
              </Tappable>
            </View>
          </Card>
        ))
      )}
      {st.stats ? (
        <Card>
          <Text style={[typography.caption, { color: colors.textSecondary }]}>
            {st.stats.rank} · level {st.stats.level} · {st.stats.xp} XP
            {st.stats.streak >= 2 ? ` · ${st.stats.streak}× streak` : ""}
          </Text>
          {st.stats.achievements.length ? (
            <Text style={[typography.caption, { color: colors.accentSuccess, marginTop: space.xs }]}>
              ★ {st.stats.achievements.join(" · ")}
            </Text>
          ) : null}
        </Card>
      ) : null}

      {/* ---------------------------------------------------------------- */}
      <Section label="Stasis — thoughts you put down" />
      <Card>
        <TextInput
          value={note}
          onChangeText={setNote}
          placeholder="hold this thought…"
          placeholderTextColor={colors.textSecondary}
          style={s.input}
        />
        <View style={s.row}>
          <Tappable
            onPress={async () => {
              if (await st.freeze(note)) setNote("");
            }}
            style={s.button}
          >
            <Text style={[typography.caption, { color: colors.textPrimary }]}>Hold it</Text>
          </Tappable>
          <Tappable onPress={() => void st.resume()} style={s.button}>
            <Text style={[typography.caption, { color: colors.textPrimary }]}>Where was I</Text>
          </Tappable>
        </View>
      </Card>
      {st.held.map((f) => (
        <Card key={f.id}>
          <Text style={[typography.body, { color: colors.textPrimary }]}>{f.utterance || "a held thought"}</Text>
          <Text style={[typography.caption, { color: colors.textSecondary, marginTop: space.xs }]}>
            {f.freshness} · {ago(f.created_ts)}
            {f.resume_count ? ` · resumed ${f.resume_count}×` : ""}
            {f.pinned ? " · pinned" : ""}
          </Text>
          <View style={s.row}>
            <Tappable onPress={() => void st.resume(f.id)} style={s.button}>
              <Text style={[typography.caption, { color: colors.textPrimary }]}>Resume</Text>
            </Tappable>
            {!f.pinned ? (
              <Tappable onPress={() => void st.pin(f.id)} style={s.button}>
                <Text style={[typography.caption, { color: colors.textSecondary }]}>Pin</Text>
              </Tappable>
            ) : null}
          </View>
        </Card>
      ))}

      {/* ---------------------------------------------------------------- */}
      <Section label="Premonition — what usually happens next" />
      <Card>
        {st.predictions.length === 0 ? (
          <Text style={[typography.caption, { color: colors.textSecondary }]}>
            Nothing to say yet. A rhythm has to repeat before it will guess — it stays quiet rather than
            inventing one.
          </Text>
        ) : (
          st.predictions.map((p, i) => (
            <Text key={i} style={[typography.body, { color: colors.textPrimary, marginBottom: space.xs }]}>
              {p.kind} · around {String(p.hour).padStart(2, "0")}:00
              {p.place ? ` · ${p.place}` : ""} · {Math.round(p.confidence * 100)}%
            </Text>
          ))
        )}
      </Card>
    </Screen>
  );
}

function statusTint(status: string | undefined, colors: any): string {
  if (status === "firsthand" || status === "corroborated") return colors.accentSuccess;
  if (status === "contested") return colors.accentError;
  if (status === "unverified") return colors.accentAttention;
  return colors.textSecondary;
}

const useS = makeThemedStyles(({ colors }) =>
  StyleSheet.create({
    input: {
      borderWidth: StyleSheet.hairlineWidth,
      borderColor: colors.borderSubtle,
      borderRadius: radius.sm,
      color: colors.textPrimary,
      paddingHorizontal: space.md,
      paddingVertical: space.sm,
      marginBottom: space.sm,
    },
    button: {
      paddingHorizontal: space.md,
      paddingVertical: space.sm,
      borderRadius: radius.sm,
      borderWidth: StyleSheet.hairlineWidth,
      borderColor: colors.borderSubtle,
      marginRight: space.sm,
      alignItems: "center",
    },
    row: { flexDirection: "row", marginTop: space.sm },
    meterTrack: {
      height: 4,
      borderRadius: 2,
      backgroundColor: colors.borderSubtle,
      marginTop: space.sm,
      overflow: "hidden",
    },
    meterFill: { height: 4, borderRadius: 2 },
  })
);
