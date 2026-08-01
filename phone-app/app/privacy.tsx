import React from "react";
import { View, Text, Switch, TextInput, StyleSheet, ActivityIndicator } from "react-native";
import { Screen } from "../src/ui/components/Screen";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { Card, Section } from "../src/ui/components/Card";
import { EmptyState } from "../src/ui/components/EmptyState";
import { Tappable } from "../src/ui/components/Tappable";
import { useTheme, makeThemedStyles } from "../src/ui/theme/useTheme";
import { typography } from "../src/ui/theme/typography";
import { space } from "../src/ui/theme/spacing";
import { useBrainStore } from "../src/state/useBrainStore";
import { usePrivacyStore, Biometric } from "../src/state/usePrivacyStore";

/**
 * Privacy — the shields, on the device that can actually raise them.
 *
 * Private zones, quiet hours, retention and the two biometric recalls were
 * reachable only from the Mac's own web panel. For most of them that is merely
 * inconvenient. For PRIVATE ZONES it made the feature close to unusable: a zone
 * is created at the CURRENT POSITION, and the Mac does not move. "Mark this
 * room as private" from the panel means carrying the Brain into the room.
 *
 * The screen shows no coordinates — not for the zones it lists and not for the
 * one it is about to create. A list of the exact locations you consider private
 * is a worse artefact than the thing it protects you from, and the wearer knows
 * where they are standing without being told.
 */

function Row({ label, sub, status, tone, children, last }: {
  label: string; sub?: string; status?: string;
  tone?: "ok" | "warn" | "muted";
  children: React.ReactNode; last?: boolean;
}) {
  const s = useS();
  const { colors } = useTheme();
  const tint = tone === "ok" ? colors.accentSuccess
    : tone === "warn" ? colors.accentAttention
    : colors.textSecondary;
  return (
    <View style={[s.row, last ? s.rowLast : null]}>
      <View style={{ flex: 1, paddingRight: 12 }}>
        <Text style={[typography.body, { color: colors.textPrimary }]}>{label}</Text>
        {sub ? <Text style={[typography.caption, { color: colors.textSecondary, marginTop: 2 }]}>{sub}</Text> : null}
        {status ? <Text style={[typography.caption, { color: tint, marginTop: 4 }]}>{status}</Text> : null}
      </View>
      {children}
    </View>
  );
}

/** Faces and voices, drawn by the same component because they are the same
 *  bargain: a template of your body, held so a machine can recognise you. */
function BiometricCard({ which, title, blurb, b }: {
  which: "faces" | "voices"; title: string; blurb: string; b: Biometric;
}) {
  const s = useS();
  const { colors, platinum } = useTheme();
  const st = usePrivacyStore();
  const [busy, setBusy] = React.useState("");

  if (!b.available) {
    return (
      <Card>
        <Text style={[typography.body, { color: colors.textPrimary }]}>{title}</Text>
        <Text style={[typography.caption, { color: colors.textSecondary, marginTop: space.sm }]}>
          Your Brain can’t offer this — the recogniser isn’t installed. This is not the same as it being
          switched off.
        </Text>
      </Card>
    );
  }

  const run = (k: string, fn: () => Promise<unknown>) => async () => {
    setBusy(k); await fn(); setBusy("");
  };

  return (
    <Card>
      <Text style={[typography.caption, { color: colors.textSecondary, marginBottom: space.md }]}>{blurb}</Text>

      {/* The consent, in the Brain's own words. Rendered verbatim because the
          acceptance is recorded against a VERSION of exactly this text — a
          paraphrase here would record agreement to something never read. */}
      {b.consentText ? (
        <View style={s.consent}>
          <Text style={[typography.eyebrow, { color: colors.accentAttention }]}>
            {b.consented ? `AGREED · ${b.consentVersion}` : "READ THIS FIRST"}
          </Text>
          <Text style={[typography.caption, { color: colors.textPrimary, marginTop: space.sm }]}>
            {b.consentText}
          </Text>
          <Tappable
            onPress={run("consent", () => st.setConsent(which, !b.consented))}
            style={s.button}
            accessibilityLabel={b.consented ? `Withdraw consent for ${title}` : `Agree for ${title}`}
          >
            {busy === "consent" ? <ActivityIndicator /> : (
              <Text style={[typography.body, { color: colors.textPrimary }]}>
                {b.consented ? "Withdraw" : "I agree"}
              </Text>
            )}
          </Tappable>
        </View>
      ) : null}

      <Row
        label="Recognise them"
        sub={`Match what’s in front of you against what you’ve stored. ${b.enrolled} held${b.unnamed ? `, ${b.unnamed} of them unnamed` : ""}.`}
        status={
          !b.model ? "No recogniser is installed on your Brain."
          : !b.consented ? "Needs your agreement above."
          : !b.ambient ? "Ambient recognition isn’t permitted where you are."
          : ""
        }
        tone="warn"
      >
        <Switch
          value={b.enabled}
          disabled={!b.model || !b.consented || !b.ambient}
          onValueChange={(v) => void st.setBiometric(which, "enabled", v)}
          accessibilityLabel={`Recognise ${which}`}
          trackColor={{ true: colors.accentMemory, false: colors.borderSubtle }}
          thumbColor={platinum.well}
        />
      </Row>
      <Row
        label="Enrol on sight"
        sub="Store a new template the first time someone is seen, without asking. You get the recall you wanted; they were never asked."
        status={b.autoEnrol ? "New people are being stored without being asked." : ""}
        tone="warn"
        last
      >
        <Switch
          value={b.autoEnrol}
          disabled={!b.enabled}
          onValueChange={(v) => void st.setBiometric(which, "autoEnrol", v)}
          accessibilityLabel={`Enrol ${which} on sight`}
          trackColor={{ true: colors.accentMemory, false: colors.borderSubtle }}
          thumbColor={platinum.well}
        />
      </Row>
    </Card>
  );
}

export default function Privacy() {
  const s = useS();
  const { colors } = useTheme();
  const connected = useBrainStore((x) => x.macMini.connected);
  const st = usePrivacyStore();

  const [zoneName, setZoneName] = React.useState("");
  const [zoneErr, setZoneErr] = React.useState("");
  const [adding, setAdding] = React.useState(false);
  const [quiet, setQuiet] = React.useState("");

  React.useEffect(() => {
    if (connected) void st.refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected]);
  React.useEffect(() => { setQuiet(st.quietHours); }, [st.quietHours]);

  const addZone = async () => {
    setAdding(true);
    const r = await st.addZoneHere(zoneName);
    setAdding(false);
    setZoneErr(r.ok ? "" : r.error || "couldn’t add that");
    if (r.ok) setZoneName("");
  };

  if (!connected) {
    return (
      <Screen>
        <ScreenHeader title="Privacy" eyebrow="Your Brain" />
        <EmptyState
          title="Connect your Mac mini"
          hint="The shields live on your Brain — it is the thing that would otherwise be capturing."
        />
      </Screen>
    );
  }

  if (st.loaded && !st.reachable) {
    return (
      <Screen>
        <ScreenHeader title="Privacy" eyebrow="Your Brain" />
        <EmptyState
          title="Couldn’t reach your Brain"
          hint="None of these can be read or changed from here right now. This is not “no shields are up” — the Brain keeps whatever it was already doing."
        />
      </Screen>
    );
  }

  return (
    <Screen>
      <ScreenHeader
        title="Privacy"
        eyebrow="Your Brain"
        subtitle={
          st.insideZone ? `Capture suspended — you’re inside ${st.insideZone}.`
          : st.veiled ? "The shield is up right now."
          : "The shield is down — your Brain is capturing."
        }
      />

      {/* ------------------------------------------------------------ zones -- */}
      <Section label="Private zones" first />
      <Card>
        <Text style={[typography.caption, { color: colors.textSecondary }]}>
          Inside a zone the Brain captures <Text style={{ color: colors.textPrimary }}>nothing</Text> — the same
          shield Incognito raises, so the ear, captions, answer-ahead, the memory ring and face recall all go quiet
          together. A zone is where you are standing when you make it; your phone is the only part of this that
          knows that, which is why it lives here.
        </Text>

        {st.zones.length === 0 ? (
          <Text style={[typography.caption, { color: colors.textSecondary, marginTop: space.lg }]}>
            No zones yet.
          </Text>
        ) : (
          <View style={{ marginTop: space.lg }}>
            {st.zones.map((z) => (
              <View key={z.name} style={s.zoneRow}>
                <View style={{ flex: 1 }}>
                  <Text style={[typography.body, { color: colors.textPrimary }]}>{z.name}</Text>
                  <Text style={[typography.caption, { color: z.inside ? colors.accentSuccess : colors.textSecondary }]}>
                    {z.inside ? `You’re inside — capture suspended · ${z.radiusM} m` : `${z.radiusM} m across`}
                  </Text>
                </View>
                <Tappable
                  onPress={() => void st.removeZone(z.name)}
                  accessibilityLabel={`Remove ${z.name}`}
                  style={s.remove}
                >
                  <Text style={[typography.caption, { color: colors.accentAttention }]}>Remove</Text>
                </Tappable>
              </View>
            ))}
          </View>
        )}

        <View style={{ marginTop: space.lg }}>
          <TextInput
            value={zoneName}
            onChangeText={setZoneName}
            placeholder="name this place — “the flat”, “the clinic”"
            placeholderTextColor={colors.textSecondary}
            accessibilityLabel="Zone name"
            style={s.input}
          />
          <Tappable
            onPress={addZone}
            disabled={adding || st.zones.length >= st.maxZones}
            accessibilityLabel="Make here a private zone"
            style={s.button}
          >
            {adding ? <ActivityIndicator /> : (
              <Text style={[typography.body, { color: colors.textPrimary }]}>Make here private</Text>
            )}
          </Tappable>
          {st.zones.length >= st.maxZones && st.maxZones > 0 ? (
            <Text style={[typography.caption, { color: colors.accentAttention, marginTop: space.sm }]}>
              {`${st.maxZones} zones is the limit — every one is checked on every position report.`}
            </Text>
          ) : null}
          {zoneErr ? (
            <Text style={[typography.caption, { color: colors.accentAttention, marginTop: space.sm }]}>{zoneErr}</Text>
          ) : null}
          {!st.hasFix ? (
            <Text style={[typography.caption, { color: colors.textSecondary, marginTop: space.sm }]}>
              Your Brain doesn’t have a recent position from this phone yet. Making a zone takes a fresh one.
            </Text>
          ) : null}
        </View>
      </Card>

      {/* ------------------------------------------------------- quiet hours -- */}
      <Section label="Quiet hours" />
      <Card>
        <Text style={[typography.caption, { color: colors.textSecondary }]}>
          A window that raises the shield by itself — cloud off, capture paused. Written as{" "}
          <Text style={{ color: colors.textPrimary }}>22:00-07:00</Text>. Leave it empty to turn it off.
        </Text>
        <TextInput
          value={quiet}
          onChangeText={setQuiet}
          onSubmitEditing={() => void st.setQuietHours(quiet.trim())}
          onBlur={() => void st.setQuietHours(quiet.trim())}
          placeholder="22:00-07:00"
          placeholderTextColor={colors.textSecondary}
          autoCapitalize="none"
          accessibilityLabel="Quiet hours"
          style={[s.input, { marginTop: space.lg }]}
        />
        {st.lastError && st.lastError !== "consent-required" ? (
          <Text style={[typography.caption, { color: colors.accentAttention, marginTop: space.sm }]}>
            {st.lastError === "unreachable" || st.lastError === "not-connected"
              ? "Your Brain didn’t take that — nothing changed."
              : `Your Brain refused that: ${st.lastError}`}
          </Text>
        ) : null}
      </Card>

      {/* ---------------------------------------------------------- faces --- */}
      <Section label="Faces" />
      <BiometricCard
        which="faces"
        title="Face recall"
        blurb="A face template is the biometric itself — not a photo, and not something the person can change if it leaks. It never leaves your Brain."
        b={st.faces}
      />

      <Section label="Voices" />
      <BiometricCard
        which="voices"
        title="Voice recall"
        blurb="A voiceprint is the same bargain as a face, made from how someone sounds. It is what lets the room read compare against a person’s own baseline instead of a stranger’s."
        b={st.voices}
      />

      {st.lastError === "consent-required" ? (
        <Card accent={colors.accentAttention}>
          <Text style={[typography.eyebrow, { color: colors.accentAttention }]}>NOT TURNED ON</Text>
          <Text style={[typography.body, { color: colors.textPrimary, marginTop: space.sm }]}>
            Recognition needs your agreement first. The switch stayed off.
          </Text>
        </Card>
      ) : null}
    </Screen>
  );
}

const useS = makeThemedStyles(({ colors, platinum }) =>
  StyleSheet.create({
    row: {
      flexDirection: "row", alignItems: "center", paddingVertical: space.md,
      borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.borderSubtle,
    },
    rowLast: { borderBottomWidth: 0 },
    zoneRow: {
      flexDirection: "row", alignItems: "center", paddingVertical: space.md,
      borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.borderSubtle,
    },
    remove: { paddingHorizontal: space.md, paddingVertical: space.sm },
    consent: {
      backgroundColor: platinum.face2,
      padding: space.md,
      marginBottom: space.md,
      borderWidth: 1.5,
      borderTopColor: platinum.sh, borderLeftColor: platinum.sh,
      borderBottomColor: platinum.hi, borderRightColor: platinum.hi,
    },
    input: {
      color: colors.textPrimary,
      backgroundColor: platinum.well,
      paddingHorizontal: space.md, paddingVertical: space.md,
      borderWidth: 1.5,
      borderTopColor: platinum.sh, borderLeftColor: platinum.sh,
      borderBottomColor: platinum.hi, borderRightColor: platinum.hi,
    },
    button: {
      alignItems: "center", marginTop: space.md, paddingVertical: space.md,
      backgroundColor: platinum.face,
      borderWidth: 1.5,
      borderTopColor: platinum.hi, borderLeftColor: platinum.hi,
      borderBottomColor: platinum.sh, borderRightColor: platinum.sh,
    },
  })
);
