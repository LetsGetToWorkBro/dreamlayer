import React from "react";
import { View, Text, StyleSheet, ScrollView } from "react-native";
import { useBrainStore, LongBrief } from "../src/state/useBrainStore";
import { useMemoryStore } from "../src/state/useMemoryStore";
import { Screen } from "../src/ui/components/Screen";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { Card, Section } from "../src/ui/components/Card";
import { EmptyState } from "../src/ui/components/EmptyState";
import { PrimaryButton } from "../src/ui/components/PrimaryButton";
import { colors } from "../src/ui/theme/colors";
import { typography } from "../src/ui/theme/typography";
import { radius, space } from "../src/ui/theme/spacing";

const DAY = 86_400_000;

function stamp(ts: number): string {
  try {
    return new Date(ts).toLocaleString([], {
      weekday: "short", hour: "numeric", minute: "2-digit",
    });
  } catch {
    return "";
  }
}

/**
 * The extended brief. The short brief is the two-sentence glance the glasses
 * wake to; this is the full one — agenda, what's due, who's waiting on you,
 * notable messages, and a line on yesterday — composed by the Brain on demand
 * and kept here so you can read it whenever, even offline.
 */
export default function Brief() {
  const macConnected = useBrainStore((s) => s.macMini.connected);
  const getLongBrief = useBrainStore((s) => s.getLongBrief);
  const stored = useBrainStore((s) => s.longBrief);
  const memories = useMemoryStore((s) => s.memories);

  const [brief, setBrief] = React.useState<LongBrief | null>(stored);
  const [loading, setLoading] = React.useState(false);

  const compose = React.useCallback(async () => {
    setLoading(true);
    // hand the Brain what only the phone holds: open promises and the moments
    // kept since yesterday morning.
    const cutoff = Date.now() - DAY;
    const commitments = memories
      .filter((m) => m.kind === "Promise")
      .map((m) => m.summary);
    const yesterday = memories
      .filter((m) => m.ts >= cutoff && m.kind !== "Promise")
      .map((m) => m.summary);
    const out = await getLongBrief({ commitments, memories: yesterday });
    if (out) setBrief(out);
    setLoading(false);
  }, [getLongBrief, memories]);

  return (
    <Screen>
      <ScreenHeader
        title="The brief"
        eyebrow="Your day, in full"
        subtitle={brief ? `Composed ${stamp(brief.ts)}` : undefined}
      />

      {!macConnected ? (
        <EmptyState
          title="Connect your Mac mini"
          hint="The extended brief is composed on your Mac mini from your agenda, messages, promises, and yesterday's memories. Pair one to read it here."
        />
      ) : (
        <>
          <View style={{ marginBottom: space.lg }}>
            <PrimaryButton
              label={loading ? "Composing…" : brief ? "Refresh the brief" : "Compose today's brief"}
              onPress={() => { if (!loading) compose(); }}
            />
          </View>

          {brief === null ? (
            <EmptyState
              title="No brief yet today"
              hint="Compose one and it's kept here — agenda, what's due, who's waiting on you, and a line on yesterday."
            />
          ) : (
            <>
              {brief.text ? (
                <Card delay={0}>
                  <Text style={[typography.eyebrow, { color: colors.accentMemory }]}>Summary</Text>
                  <Text style={[typography.body, { color: colors.textPrimary, marginTop: space.sm, lineHeight: 24 }]}>
                    {brief.text}
                  </Text>
                </Card>
              ) : null}

              {brief.sections.map((sec, si) => (
                <View key={sec.title}>
                  <Section label={sec.title} first={false} accent={colors.textSecondary} />
                  <Card delay={si * 45}>
                    {sec.items.map((it, i) => (
                      <View key={i} style={s.row}>
                        <View style={s.dot} />
                        <Text style={[typography.body, { color: colors.textPrimary, flex: 1 }]}>{it}</Text>
                      </View>
                    ))}
                  </Card>
                </View>
              ))}
            </>
          )}
        </>
      )}
    </Screen>
  );
}

const s = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "flex-start", gap: space.md, paddingVertical: space.xs },
  dot: {
    width: 6, height: 6, borderRadius: 3, marginTop: 8,
    backgroundColor: colors.accentMemory,
  },
});
