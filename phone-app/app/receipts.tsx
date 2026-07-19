import React, { useEffect, useCallback } from "react";
import { View, Text, ScrollView, StyleSheet, Pressable, ActivityIndicator } from "react-native";

import { useReceiptStore } from "../src/state/useReceiptStore";
import { ReceiptRecord } from "../src/crypto/receiptVerify";
import { Screen } from "../src/ui/components/Screen";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { Card, Section } from "../src/ui/components/Card";
import { EmptyState } from "../src/ui/components/EmptyState";
import { colors } from "../src/ui/theme/colors";
import { typography } from "../src/ui/theme/typography";
import { space } from "../src/ui/theme/spacing";

function fingerprint(k: string): string {
  return k ? `${k.slice(0, 8)}…${k.slice(-4)}` : "";
}
function clockTime(ts: number): string {
  try {
    return new Date((Number(ts) || 0) * 1000).toLocaleTimeString();
  } catch {
    return "";
  }
}

function Verdict() {
  const { result, keyChanged, firstSeen, pubkey, records, repin } = useReceiptStore();
  const count = records.length;
  if (!result) return null;

  let tone: string = colors.statusPaused;
  let head = "Not verified";
  let sub = "";
  let showRepin = false;
  if (keyChanged) {
    tone = colors.accentError;
    head = "This Brain's key changed";
    sub =
      "The signing key differs from the one this phone pinned. If you just reinstalled your Brain, re-pin below — otherwise someone may be impersonating it. Nothing here is trusted until you do.";
    showRepin = true;
  } else if (!result.signed) {
    tone = colors.statusPaused;
    head = "Unsigned ledger";
    sub = `Chain ${result.chainIntact ? "intact" : "broken"} — but this Brain isn't signing receipts yet.`;
  } else if (result.ok) {
    tone = colors.accentSuccess;
    head = "Verified";
    const of = result.attestedCount && result.attestedCount > count ? ` of ${result.attestedCount}` : "";
    sub = `Signed by this device · ${count}${of} ${count === 1 ? "entry" : "entries"} · chain intact`;
  } else if (result.unattestedAppend) {
    tone = colors.accentError;
    head = "Tampering detected · unattested entries";
    sub = "The ledger carries entries beyond its signed length — records were appended without the Brain's key.";
  } else if (!result.chainIntact) {
    tone = colors.accentError;
    head = `Tampering detected · entry ${(result.firstBroken ?? 0) + 1}`;
    sub = "A hash-chain link (or the signed length anchor) is broken — an entry was altered or removed after signing.";
  } else if (!result.sequenceComplete) {
    tone = colors.accentError;
    head = "Tampering detected · missing entry";
    sub = "A sequence number is missing — an entry was deleted.";
  } else if (!result.signatureValid) {
    tone = colors.accentError;
    head = "Tampering detected · bad signature";
    sub = "A signature failed — a record was changed after it was signed.";
  } else if (result.tailShort) {
    tone = colors.accentAttention;
    head = "Recent entries may be missing";
    sub = `The signed length is ${result.attestedCount}, but only ${count} were returned. The shown entries are authentic — tap Re-verify; if this persists, the tail was truncated.`;
  } else {
    // signed, but no verifiable length anchor to confirm completeness
    tone = colors.accentAttention;
    head = "Can't confirm completeness";
    sub = "The shown entries are authentic, but the signed length anchor is missing — the Brain may be hiding recent activity. Re-verify; if it persists, treat with suspicion.";
  }

  return (
    <Card style={{ borderLeftWidth: 3, borderLeftColor: tone, marginBottom: space.md }}>
      <Text style={[typography.title, { color: tone }]}>{head}</Text>
      <Text style={[typography.body, { color: colors.textSecondary, marginTop: space.xs }]}>{sub}</Text>
      {pubkey ? (
        <Text style={[typography.caption, { color: colors.textSecondary, marginTop: space.sm, fontFamily: "monospace" }]}>
          key {fingerprint(pubkey)}
          {firstSeen ? "  · pinned to this phone" : ""}
        </Text>
      ) : null}
      {showRepin ? (
        <Pressable
          onPress={() => repin()}
          style={({ pressed }) => [st.repin, { opacity: pressed ? 0.6 : 1 }]}
          accessibilityRole="button"
        >
          <Text style={[typography.caption, { color: colors.accentError, fontWeight: "600" }]}>
            I reinstalled the Brain — trust the new key
          </Text>
        </Pressable>
      ) : null}
    </Card>
  );
}

function Entry({ rec, broken }: { rec: ReceiptRecord; broken: boolean }) {
  return (
    <Card
      style={{
        marginBottom: space.sm,
        ...(broken ? { borderLeftWidth: 3, borderLeftColor: colors.accentError } : {}),
      }}
    >
      <View style={st.row}>
        <Text style={[typography.body, { color: colors.textPrimary, flex: 1 }]} numberOfLines={2}>
          {rec.text || rec.kind}
        </Text>
        <Text style={[typography.caption, { color: colors.textSecondary }]}>{clockTime(rec.ts)}</Text>
      </View>
      <Text style={[typography.caption, { color: colors.textSecondary, marginTop: space.xs, fontFamily: "monospace" }]}>
        {rec.kind} · seq {rec.seq} · #{(rec.prev || "genesis").slice(0, 10)}
      </Text>
    </Card>
  );
}

export default function Receipts() {
  const { records, result, loaded, loading, connected, error, load } = useReceiptStore();
  useEffect(() => {
    load();
  }, [load]);
  const reverify = useCallback(() => load(), [load]);

  // records are oldest-first; a tamper at firstBroken taints it and everything after.
  const brokenFrom =
    result && !result.ok && result.firstBroken != null ? result.firstBroken : Number.POSITIVE_INFINITY;

  return (
    <Screen>
      <ScreenHeader title="Privacy receipt" subtitle="What your Brain did — and proof it's unaltered" />
      {loaded && !connected ? (
        <EmptyState glyph="◍" title="No Brain paired" hint="Pair your Mac Brain to see and verify its activity receipt." />
      ) : (
        <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={{ paddingBottom: space.xxxl }}>
          <Verdict />
          <Pressable
            onPress={reverify}
            disabled={loading}
            style={({ pressed }) => [st.btn, { opacity: pressed || loading ? 0.6 : 1 }]}
            accessibilityRole="button"
          >
            {loading ? (
              <ActivityIndicator color={colors.surfaceElevated} />
            ) : (
              <Text style={[typography.body, { color: colors.surfaceElevated, fontWeight: "600" }]}>Re-verify</Text>
            )}
          </Pressable>

          {error ? (
            <Text style={[typography.caption, { color: colors.accentError, marginTop: space.md }]}>
              Couldn't reach the Brain: {error}
            </Text>
          ) : null}

          {records.length ? (
            <>
              <Section label="Activity — newest first" />
              {records
                .map((rec, i) => ({ rec, i }))
                .reverse()
                .map(({ rec, i }) => (
                  <Entry key={`${rec.seq}-${i}`} rec={rec} broken={i >= brokenFrom} />
                ))}
            </>
          ) : loaded && connected && !error ? (
            <EmptyState glyph="◉" title="Nothing recorded yet" hint="As your Brain does things, they'll appear here — each one sealed and signed." />
          ) : null}
        </ScrollView>
      )}
    </Screen>
  );
}

const st = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between", gap: space.sm },
  repin: {
    marginTop: space.md,
    alignSelf: "flex-start",
    borderWidth: 1,
    borderColor: colors.accentError,
    borderRadius: 8,
    paddingVertical: space.xs,
    paddingHorizontal: space.sm,
  },
  btn: {
    backgroundColor: colors.accentMemory,
    borderRadius: 10,
    paddingVertical: space.md,
    alignItems: "center",
    justifyContent: "center",
  },
});
