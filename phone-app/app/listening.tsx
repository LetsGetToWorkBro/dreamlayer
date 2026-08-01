import React from "react";
import { View, Text, Switch, StyleSheet, ActivityIndicator } from "react-native";
import { Screen } from "../src/ui/components/Screen";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { Card, Section } from "../src/ui/components/Card";
import { EmptyState } from "../src/ui/components/EmptyState";
import { Tappable } from "../src/ui/components/Tappable";
import { useTheme, makeThemedStyles } from "../src/ui/theme/useTheme";
import { typography } from "../src/ui/theme/typography";
import { space } from "../src/ui/theme/spacing";
import { useBrainStore } from "../src/state/useBrainStore";
import { useEarStore, EarSwitches } from "../src/state/useEarStore";

/**
 * Listening — everything the Brain hears, on the surface you actually carry.
 *
 * Live captions, the interpreter, the room read and Name Capture each shipped
 * with a switch on the Mac's own web panel and nothing on the phone. A setting
 * you can only reach by opening a laptop is, for most of a day, a setting that
 * does not exist — and every one of these is something you want to change in
 * the moment you walk into a room, not the evening before.
 *
 * The rules this screen keeps, all of them the same rule:
 *
 *   * A SWITCH IS NOT A STATUS. Under each one is what it is actually doing —
 *     the count, the "no microphone is open", the "the pack isn't installed".
 *     A green switch over silence is the failure this screen exists to avoid.
 *   * NOTHING WORKS WITHOUT THE MICROPHONE, and the screen says so rather than
 *     letting four switches sit there looking live above a closed ear.
 *   * THE WRITE HAPPENS ON THE BRAIN. If it fails, the switch does not move.
 *   * THE ONE SWITCH THAT WRITES WITHOUT ASKING SAYS SO in its own words.
 */

/** One Brain-owned switch: label, what it does, what it is DOING, and the
 *  toggle. `busy` disables the whole row while a write is in flight so a fast
 *  double-tap cannot race two patches to the same key. */
function SwitchRow({
  label, sub, status, statusTone, value, onChange, disabled, busy, last,
}: {
  label: string;
  sub: string;
  status?: string;
  statusTone?: "ok" | "warn" | "muted";
  value: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  busy?: boolean;
  last?: boolean;
}) {
  const s = useS();
  const { colors, platinum } = useTheme();
  const tone =
    statusTone === "ok" ? colors.accentSuccess
    : statusTone === "warn" ? colors.accentAttention
    : colors.textSecondary;
  return (
    <View style={[s.row, last ? s.rowLast : null, disabled ? s.rowOff : null]}>
      <View style={{ flex: 1, paddingRight: 12 }}>
        <Text style={[typography.body, { color: colors.textPrimary }]}>{label}</Text>
        <Text style={[typography.caption, { color: colors.textSecondary, marginTop: 2 }]}>{sub}</Text>
        {status ? (
          <Text style={[typography.caption, { color: tone, marginTop: 4 }]}>{status}</Text>
        ) : null}
      </View>
      {busy ? (
        <ActivityIndicator accessibilityLabel="Saving" />
      ) : (
        <Switch
          value={value}
          onValueChange={onChange}
          disabled={disabled}
          accessibilityLabel={label}
          trackColor={{ true: colors.accentMemory, false: colors.borderSubtle }}
          thumbColor={platinum.well}
        />
      )}
    </View>
  );
}

export default function Listening() {
  const s = useS();
  const { colors } = useTheme();
  const connected = useBrainStore((x) => x.macMini.connected);
  const st = useEarStore();
  const { switches: sw, runtime: rt } = st;
  const [busyKey, setBusyKey] = React.useState<keyof EarSwitches | "">("");

  React.useEffect(() => {
    if (connected) void st.refresh();
    // one read per connection change — these are settings, not a feed
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected]);

  const flip = (key: keyof EarSwitches) => async (v: boolean) => {
    setBusyKey(key);
    await st.set(key, v as never);
    setBusyKey("");
  };

  if (!connected) {
    return (
      <Screen>
        <ScreenHeader title="Listening" eyebrow="Your Brain" />
        <EmptyState
          title="Connect your Mac mini"
          hint="The ear runs on your Brain — the microphone, the transcript and every switch below live there, not in this app."
        />
      </Screen>
    );
  }

  if (st.loaded && !st.reachable) {
    return (
      <Screen>
        <ScreenHeader title="Listening" eyebrow="Your Brain" />
        <EmptyState
          title="Couldn’t reach your Brain"
          hint="These switches are stored on the Mac mini, so none of them can be read or changed from here right now. This is not “everything is off”."
        />
      </Screen>
    );
  }

  const mic = rt.listening || rt.remoteListening;
  /** Everything below the ear needs an open microphone. Rather than let four
   *  live-looking switches sit above a closed one, each says why. */
  const needsMic = sw.listen_enabled && !mic
    ? "The switch is on, but no microphone is open yet."
    : "";
  const off = !sw.listen_enabled;
  const offNote = "Turn Listening on first — nothing is heard without it.";

  return (
    <Screen>
      <ScreenHeader
        title="Listening"
        eyebrow="Your Brain"
        subtitle={
          mic
            ? `${rt.heardCount} utterance${rt.heardCount === 1 ? "" : "s"} heard this session`
            : "Off. Nothing is being heard."
        }
      />

      {st.lastError ? (
        <Card accent={colors.accentAttention}>
          <Text style={[typography.eyebrow, { color: colors.accentAttention }]}>NOT SAVED</Text>
          <Text style={[typography.body, { color: colors.textPrimary, marginTop: space.sm }]}>
            {st.lastError === "unreachable" || st.lastError === "not-connected"
              ? "Your Brain didn’t take that change, so the switch stayed where it was. Nothing was turned on."
              : `Your Brain refused that change: ${st.lastError}`}
          </Text>
        </Card>
      ) : null}

      {/* ------------------------------------------------------------ ear -- */}
      <Section label="The microphone" first />
      <Card>
        <SwitchRow
          label="Listening"
          sub="The Brain’s own microphone transcribes speech entirely on-device and folds what it hears into your memory. It hears everyone in range, not just you."
          status={
            rt.listening ? `Open — ${rt.heardCount} heard.`
            : sw.listen_enabled ? "On, but no microphone is open. Is the Sharp Ears pack installed?"
            : "Off."
          }
          statusTone={rt.listening ? "ok" : sw.listen_enabled ? "warn" : "muted"}
          value={sw.listen_enabled}
          onChange={flip("listen_enabled")}
          busy={busyKey === "listen_enabled"}
        />
        <SwitchRow
          label="Use this phone as the microphone"
          sub="Stream from the phone in your pocket instead of (or besides) the Mac’s own mic — the Brain is in another room most of the day."
          status={rt.remoteListening ? "The phone is feeding the ear." : sw.remote_listen_enabled ? "Allowed, but nothing is streaming." : ""}
          statusTone={rt.remoteListening ? "ok" : "muted"}
          value={sw.remote_listen_enabled}
          onChange={flip("remote_listen_enabled")}
          busy={busyKey === "remote_listen_enabled"}
          last
        />
      </Card>
      <Text style={[typography.caption, s.footnote]}>
        The Veil wins over every switch on this screen: nothing is heard, read or kept while Incognito, in quiet
        hours, or inside a private zone.
      </Text>

      {/* -------------------------------------------------------- captions -- */}
      <Section label="What it does with what it hears" />
      <Card>
        <SwitchRow
          label="Live captions"
          sub="Put what’s said on the glass as it’s said. Goes in your receipt when it goes on."
          status={off ? offNote : needsMic}
          statusTone="warn"
          value={sw.captions_enabled}
          onChange={flip("captions_enabled")}
          disabled={off}
          busy={busyKey === "captions_enabled"}
        />
        <SwitchRow
          label="Answer-ahead"
          sub="Someone asks you something; the Brain pulls the answer out of what you already know and puts it on the glass in time to say it yourself."
          status={off ? offNote : needsMic}
          statusTone="warn"
          value={sw.answer_ahead_enabled}
          onChange={flip("answer_ahead_enabled")}
          disabled={off}
          busy={busyKey === "answer_ahead_enabled"}
        />
        <SwitchRow
          label="Interpreter"
          sub="Someone speaks a language you don’t; the Brain carries the meaning across on-device. There is no transcript of the original to store — only what it meant."
          status={
            off ? offNote
            : !rt.canInterpret ? "The Interpreter pack isn’t installed on your Brain."
            : rt.interpretProved ? `${rt.interpretedCount} line${rt.interpretedCount === 1 ? "" : "s"} carried across.`
            : sw.interpret_enabled ? (needsMic || "On — nothing carried across yet.")
            : ""
          }
          statusTone={rt.interpretProved ? "ok" : off || !rt.canInterpret ? "warn" : "muted"}
          value={sw.interpret_enabled}
          onChange={flip("interpret_enabled")}
          disabled={off}
          busy={busyKey === "interpret_enabled"}
        />
        <SwitchRow
          label="Read the room"
          sub="How something was said — voice stress and word choice, on-device, nothing stored. This reads delivery, not truth: it cannot tell you whether something is a lie."
          status={
            off ? offNote
            : rt.truthProved ? `${rt.truthReads} read${rt.truthReads === 1 ? "" : "s"} drawn.`
            : sw.truth_lens_enabled ? (needsMic || "On — no read has cleared the threshold yet, which is the normal outcome for a credible speaker.")
            : ""
          }
          statusTone={rt.truthProved ? "ok" : off ? "warn" : "muted"}
          value={sw.truth_lens_enabled}
          onChange={flip("truth_lens_enabled")}
          disabled={off}
          busy={busyKey === "truth_lens_enabled"}
          last
        />
      </Card>

      {/* ----------------------------------------------------------- names -- */}
      <Section label="Names" />
      <Card>
        <SwitchRow
          label="Name capture"
          sub="Someone introduces themselves out loud and the glass asks “Remember them?”. Hearing a name saves nothing — the offer expires by itself after twelve seconds and nothing is written unless you say so."
          status={
            off ? offNote
            : sw.intro_capture_enabled
              ? (st.intro.offered
                  ? `${st.intro.kept} kept of ${st.intro.offered} offered.`
                  : (needsMic || "On — listening for someone to introduce themselves."))
              : ""
          }
          statusTone={st.intro.kept > 0 ? "ok" : off ? "warn" : "muted"}
          value={sw.intro_capture_enabled}
          onChange={flip("intro_capture_enabled")}
          disabled={off}
          busy={busyKey === "intro_capture_enabled"}
        />
        <SwitchRow
          label="Keep without asking me"
          sub="A heard introduction is saved the moment it’s heard, with no confirm step. This is the only switch on this screen that writes a name you didn’t agree to in the moment."
          status={sw.intro_auto_keep ? "Names are being kept without asking." : ""}
          statusTone="warn"
          value={sw.intro_auto_keep}
          onChange={flip("intro_auto_keep")}
          disabled={off || !sw.intro_capture_enabled}
          busy={busyKey === "intro_auto_keep"}
          last
        />
      </Card>
      <Text style={[typography.caption, s.footnote]}>
        Only a closed grammar captures — “my name is…”, “I’m…”, “this is…”, “call me…”. Ordinary conversation
        produces nothing, which is what keeps this at people who chose to give you their name rather than everyone
        within earshot. A name heard aloud is never a face.
      </Text>

      {/* An offer live on the glass, answerable from here. The glass has its own
          Keep/Skip; this is the same decision for when the phone is already in
          your hand. Deliberately shows no NAME — it is on the wearer's own
          display, and putting it here would add a surface it does not need. */}
      {st.intro.pending ? (
        <Card accent={colors.accentMemory}>
          <Text style={[typography.eyebrow, { color: colors.accentMemory }]}>SOMEONE JUST INTRODUCED THEMSELVES</Text>
          <Text style={[typography.body, { color: colors.textPrimary, marginTop: space.sm }]}>
            Their name is on your glass right now. Keep it, or let it go — it expires on its own either way.
          </Text>
          <View style={s.answers}>
            <Tappable onPress={() => void st.confirmIntro()} style={[s.answer, s.answerKeep]}>
              <Text style={[typography.body, { color: colors.textPrimary }]}>Keep</Text>
            </Tappable>
            <Tappable onPress={() => void st.dismissIntro()} style={s.answer}>
              <Text style={[typography.body, { color: colors.textSecondary }]}>Skip</Text>
            </Tappable>
          </View>
        </Card>
      ) : null}
    </Screen>
  );
}

const useS = makeThemedStyles(({ colors, platinum }) =>
  StyleSheet.create({
    row: {
      flexDirection: "row",
      alignItems: "center",
      paddingVertical: space.md,
      borderBottomWidth: StyleSheet.hairlineWidth,
      borderBottomColor: colors.borderSubtle,
    },
    rowLast: { borderBottomWidth: 0 },
    rowOff: { opacity: 0.55 },
    footnote: {
      color: colors.textSecondary,
      marginTop: space.md,
    },
    answers: { flexDirection: "row", gap: space.md, marginTop: space.lg },
    answer: {
      flex: 1,
      alignItems: "center",
      paddingVertical: space.md,
      backgroundColor: platinum.face,
      borderWidth: 1.5,
      borderTopColor: platinum.hi,
      borderLeftColor: platinum.hi,
      borderBottomColor: platinum.sh,
      borderRightColor: platinum.sh,
    },
    answerKeep: { borderTopColor: colors.accentMemory, borderLeftColor: colors.accentMemory },
  })
);
