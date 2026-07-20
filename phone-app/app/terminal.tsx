import React from "react";
import {
  View, Text, TextInput, ScrollView, StyleSheet, Platform, Pressable, Keyboard,
} from "react-native";
import { useRouter } from "expo-router";
import * as Haptics from "expo-haptics";
import { Screen } from "../src/ui/components/Screen";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { useBrainStore } from "../src/state/useBrainStore";
import { playEarcon } from "../src/services/sound";
import {
  run, startDream, banner, type Line, type Mode, type DreamState, type Tone,
} from "../src/features/dreamshell";

// A terminal is its own dark world (like the HUD), not the Platinum light chrome.
const MONO = Platform.OS === "ios" ? "Menlo" : "monospace";
const PHOS = "#2CC79A";
const TONE: Record<Tone, string> = {
  normal: PHOS, bold: "#9FE8D4", dim: "#58686F", warn: "#E0B54A", coral: "#E06B52", juno: "#9FE8D4",
};

let _seq = 0;
type Row = Line & { id: number };
const rows = (lines: Line[]): Row[] => lines.map((l) => ({ ...l, id: _seq++ }));

export default function Terminal() {
  const router = useRouter();
  const incognito = useBrainStore((s) => s.incognito);
  const setIncognito = useBrainStore((s) => s.setIncognito);
  const ask = useBrainStore((s) => s.ask);

  const [lines, setLines] = React.useState<Row[]>(() => rows(banner(useBrainStore.getState().incognito)));
  const [input, setInput] = React.useState("");
  const [mode, setMode] = React.useState<Mode>("shell");
  const dreamRef = React.useRef<DreamState | null>(null);
  const histRef = React.useRef<string[]>([]);
  const scrollRef = React.useRef<ScrollView>(null);

  const push = React.useCallback((ls: Line[]) => {
    if (!ls.length) return;
    setLines((prev) => [...prev, ...rows(ls)]);
    requestAnimationFrame(() => scrollRef.current?.scrollToEnd({ animated: true }));
  }, []);

  const rain = React.useCallback(() => {
    // a small "digital rain" flourish — a few lines of glyphs, then it settles
    const glyphs = "アカサ01ラムグラスRAMEGLASS";
    let n = 0;
    const iv = setInterval(() => {
      const s = Array.from({ length: 22 }, () => glyphs[Math.floor(Math.random() * glyphs.length)]).join("");
      push([{ t: s, tone: "dim" }]);
      if (++n >= 6) clearInterval(iv);
    }, 90);
  }, [push]);

  const submit = React.useCallback(async (raw: string) => {
    const echo: Line = { t: (mode === "dream" ? "dream> " : "layer> ") + raw, tone: "bold" };
    push([echo]);
    if (raw.trim()) histRef.current.push(raw);

    const out = run(raw, { veiled: incognito, mode, dream: dreamRef.current });
    if (out.mode !== undefined) setMode(out.mode);
    if (out.dream !== undefined) dreamRef.current = out.dream;
    push(out.lines);

    for (const e of out.effects ?? []) {
      switch (e.kind) {
        case "clear": setLines([]); break;
        case "exit": setTimeout(() => router.back(), 380); break;
        case "veil": setIncognito(e.on); break;
        case "nav": setTimeout(() => router.push(e.route as never), 240); break;
        case "juno":
          playEarcon("hey");
          Haptics.impactAsync?.(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
          break;
        case "haptic":
          Haptics.impactAsync?.(Haptics.ImpactFeedbackStyle.Medium).catch(() => {});
          break;
        case "matrix": rain(); break;
        case "glitch":
          Haptics.notificationAsync?.(Haptics.NotificationFeedbackType.Warning).catch(() => {});
          break;
        case "ask": {
          const res = await ask(e.query).catch(() => null);
          push(res?.text
            ? [{ t: res.text }, ...(res.tier ? [{ t: "· " + res.tier, tone: "dim" as Tone }] : [])]
            : [{ t: "no answer", tone: "dim" }]);
          break;
        }
      }
    }
  }, [mode, incognito, push, rain, ask, router, setIncognito]);

  const onSubmit = () => {
    const raw = input;
    setInput("");
    void submit(raw);
    Keyboard.dismiss();
  };

  return (
    <Screen scroll={false} gutters={false}>
      <ScreenHeader title="DreamShell" eyebrow="Terminal" subtitle="Your Brain's command line. Type help — or type dream." />
      <Pressable style={s.term} onPress={() => Keyboard.dismiss()} accessible={false}>
        <ScrollView
          ref={scrollRef}
          style={s.scr}
          contentContainerStyle={s.scrInner}
          keyboardShouldPersistTaps="handled"
          onContentSizeChange={() => scrollRef.current?.scrollToEnd({ animated: false })}
        >
          {lines.map((l) => (
            <Text key={l.id} style={[s.line, { color: TONE[l.tone ?? "normal"] }, l.tone === "bold" ? s.bold : null]}>
              {l.t || " "}
            </Text>
          ))}
        </ScrollView>
        <View style={s.inputRow}>
          <Text style={s.ps1}>{mode === "dream" ? "dream> " : "layer> "}</Text>
          <TextInput
            testID="term-input"
            style={s.input}
            value={input}
            onChangeText={setInput}
            onSubmitEditing={onSubmit}
            placeholder="type a command"
            placeholderTextColor="#3F8F5C"
            autoCapitalize="none"
            autoCorrect={false}
            autoComplete="off"
            spellCheck={false}
            returnKeyType="send"
            blurOnSubmit={false}
            accessibilityLabel="DreamShell command line"
          />
        </View>
      </Pressable>
    </Screen>
  );
}

// exported so a hub/labs row can jump here; the adventure opener is reused in tests
export { startDream };

const s = StyleSheet.create({
  term: { flex: 1, backgroundColor: "#08100F", margin: 12, borderRadius: 4, borderWidth: 1, borderColor: "#000", overflow: "hidden" },
  scr: { flex: 1 },
  scrInner: { padding: 12 },
  line: { fontFamily: MONO, fontSize: 13, lineHeight: 20 },
  bold: { fontWeight: "600" },
  inputRow: { flexDirection: "row", alignItems: "center", borderTopColor: "#1A2422", borderTopWidth: 1, backgroundColor: "#0A1413", paddingHorizontal: 12, paddingVertical: 8 },
  ps1: { fontFamily: MONO, fontSize: 13, color: "#9FE8D4" },
  input: { flex: 1, fontFamily: MONO, fontSize: 13, color: PHOS, padding: 0 },
});
