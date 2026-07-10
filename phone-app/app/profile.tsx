import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { useBrainStore, JunoProfile } from "../src/state/useBrainStore";
import { Screen } from "../src/ui/components/Screen";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { Card, Section } from "../src/ui/components/Card";
import { EmptyState } from "../src/ui/components/EmptyState";
import { colors } from "../src/ui/theme/colors";
import { typography } from "../src/ui/theme/typography";
import { radius, space } from "../src/ui/theme/spacing";

function Chips({ items, tint }: { items: string[]; tint: string }) {
  return (
    <View style={s.chipWrap}>
      {items.map((it, i) => (
        <View key={`${it}-${i}`} style={[s.chip, { borderColor: tint }]}>
          <Text style={[typography.caption, { color: colors.textPrimary }]}>{it}</Text>
        </View>
      ))}
    </View>
  );
}

export default function Profile() {
  const macConnected = useBrainStore((s) => s.macMini.connected || s.demoMode);
  const getProfile = useBrainStore((s) => s.getProfile);
  const [p, setP] = React.useState<JunoProfile | null>(null);
  const [loaded, setLoaded] = React.useState(false);

  React.useEffect(() => {
    let alive = true;
    (async () => {
      const prof = macConnected ? await getProfile() : null;
      if (alive) {
        setP(prof);
        setLoaded(true);
      }
    })();
    return () => {
      alive = false;
    };
  }, [macConnected, getProfile]);

  const empty =
    !!p && !p.name && p.interests.length === 0 && p.people.length === 0 && p.preferences.length === 0;

  return (
    <Screen>
      <ScreenHeader
        title="What Juno knows"
        eyebrow="Your profile"
        subtitle={p && p.observations ? `learned from ${p.observations} of your own lines` : undefined}
      />

      {!macConnected ? (
        <EmptyState
          title="Connect your Mac mini"
          hint="Juno builds your profile on the glasses and mirrors it to your Brain so you can see it here."
        />
      ) : !loaded ? (
        <EmptyState title="Loading…" hint="Reading what Juno has learned." />
      ) : !p ? (
        <EmptyState title="Couldn’t reach your Brain" hint="Is the Mac mini awake and reachable?" />
      ) : empty ? (
        <EmptyState
          title="Nothing learned yet"
          hint="As you talk with Juno on, it learns the topics you return to and remembers what you tell it — “call me Sam”, “I prefer aisle seats”."
        />
      ) : (
        <>
          {p.name ? (
            <Card>
              <Text style={[typography.eyebrow, { color: colors.accentMemory }]}>It calls you</Text>
              <Text style={[typography.display, { color: colors.textPrimary }]}>{p.name}</Text>
            </Card>
          ) : null}

          {p.interests.length ? (
            <>
              <Section label="What you return to" first accent={colors.accentMemory} />
              <Card>
                <Chips items={p.interests} tint={colors.accentMemory} />
              </Card>
            </>
          ) : null}

          {p.people.length ? (
            <>
              <Section label="Who you talk with" accent={colors.accentSuccess} />
              <Card>
                <Chips items={p.people} tint={colors.accentSuccess} />
              </Card>
            </>
          ) : null}

          {p.preferences.length ? (
            <>
              <Section label="What it remembers" accent={colors.accentAttention} />
              {p.preferences.map((pref, i) => (
                <Card key={`${pref}-${i}`} delay={i * 30}>
                  <Text style={[typography.body, { color: colors.textPrimary }]}>{pref}</Text>
                </Card>
              ))}
            </>
          ) : null}

          <Text style={[typography.caption, s.footnote]}>
            Built on-device from your own words — never other people’s, never raw audio. Say “forget that” to Juno to clear a preference.
          </Text>
        </>
      )}
    </Screen>
  );
}

const s = StyleSheet.create({
  chipWrap: { flexDirection: "row", flexWrap: "wrap", gap: space.xs },
  chip: {
    borderWidth: 1,
    borderRadius: radius.pill,
    paddingHorizontal: space.sm,
    paddingVertical: 6,
  },
  footnote: {
    color: colors.textSecondary,
    marginTop: space.md,
    marginHorizontal: space.sm,
    opacity: 0.8,
  },
});
