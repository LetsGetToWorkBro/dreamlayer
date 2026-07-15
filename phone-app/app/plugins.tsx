import React from "react";
import {
  View, Text, StyleSheet, ScrollView, TextInput, Pressable, Alert, Linking, Modal, Image,
} from "react-native";
import { usePluginStore, PluginEntry, SortKey } from "../src/state/usePluginStore";
import { useBrainStore } from "../src/state/useBrainStore";
import { Screen } from "../src/ui/components/Screen";
import { ScreenHeader } from "../src/ui/components/ScreenHeader";
import { Card } from "../src/ui/components/Card";
import { EmptyState } from "../src/ui/components/EmptyState";
import { colors } from "../src/ui/theme/colors";
import { typography } from "../src/ui/theme/typography";
import { space } from "../src/ui/theme/spacing";

type Sort = "featured" | "rating" | "downloads" | "all";
const TABS: { key: Sort; label: string }[] = [
  { key: "featured", label: "Featured" },
  { key: "rating", label: "Top rated" },
  { key: "downloads", label: "Downloads" },
  { key: "all", label: "All" },
];

function fmt(n: number): string {
  return n >= 1000 ? `${(n / 1000).toFixed(1).replace(/\.0$/, "")}k` : String(n);
}

// Plain-English gloss for each capability a plugin can ask for.
const CAP_HELP: Record<string, string> = {
  midi: "Send MIDI notes to music apps on your Mac (e.g. Ableton, VCV).",
  network: "Reach the internet to look things up.",
  vision: "Use the Brain’s on-device vision model to read what you see.",
  fs: "Read files you point it at.",
  mesh: "Talk to a GhostMode circle of nearby wearers.",
  object_lens: "Add rows to the look-at-a-thing panel.",
  glance: "Add a lens the look can route to.",
  cards: "Draw its own card on the HUD.",
  perception: "Use the fast on-glass perception tier.",
  ring: "Read your kept-memory ledger.",
  shop: "Feed prices/reviews into TasteLens.",
};

/**
 * The Plugins screen — browse the git-backed registry and manage what your
 * layer runs. Installing grants a plugin the capabilities it asks for and tells
 * the paired hub to fetch + validate + run it; the phone never runs plugin code
 * itself (docs/MARKETPLACE.md).
 */
export default function Plugins() {
  const index = usePluginStore((s) => s.index);
  const loading = usePluginStore((s) => s.loading);
  const offline = usePluginStore((s) => s.offline);
  const installedMap = usePluginStore((s) => s.installed);
  const searchFn = usePluginStore((s) => s.search);
  const hydrate = usePluginStore((s) => s.hydrate);
  const install = usePluginStore((s) => s.install);
  const remove = usePluginStore((s) => s.remove);
  const rate = usePluginStore((s) => s.rate);
  const mac = useBrainStore((s) => s.macMini);

  const [query, setQuery] = React.useState("");
  const [sort, setSort] = React.useState<Sort>("featured");
  const [detail, setDetail] = React.useState<PluginEntry | null>(null);

  React.useEffect(() => {
    hydrate();
  }, [hydrate]);

  const list = searchFn(query, sort as SortKey);
  const macTarget = mac.connected ? { url: mac.url, token: mac.token } : null;

  const onInstall = (p: PluginEntry) => {
    const perms = p.requires.length
      ? p.requires.map((r) => `•  ${r} — ${CAP_HELP[r] || "a capability it requested"}`).join("\n")
      : "No special access — it only extends the layer's own surfaces.";
    Alert.alert(
      `Install ${p.name}?`,
      `${p.official ? "Official — built by the DreamLayer team.\n\n" : ""}` +
        `This plugin will be able to:\n${perms}\n\n` +
        (macTarget
          ? "It's validated on your Mac (integrity + capability scan + smoke test) before it runs."
          : "Queued — it installs and is validated on your hub the next time one is paired."),
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Install",
          onPress: async () => {
            const r = await install(p, macTarget);
            if (!r.ok) {
              Alert.alert(`Couldn't install ${p.name}`, r.error || "Please try again.");
            }
          },
        },
      ],
    );
  };

  const onRemove = (p: PluginEntry) => {
    Alert.alert(`Remove ${p.name}?`, "It'll stop running on your layer.", [
      { text: "Cancel", style: "cancel" },
      { text: "Remove", style: "destructive", onPress: () => remove(p.name, macTarget) },
    ]);
  };

  return (
    <Screen>
      <ScreenHeader
        title="Plugins"
        eyebrow="Build on the layer"
        subtitle="Community plugins — validated before they run."
      />

      <TextInput
        style={st.search}
        placeholder="Search plugins…"
        placeholderTextColor={colors.textSecondary}
        value={query}
        onChangeText={setQuery}
        autoCapitalize="none"
      />

      <View style={st.tabs}>
        {TABS.map((t) => (
          <Pressable
            key={t.key}
            onPress={() => setSort(t.key)}
            style={[st.tab, sort === t.key && st.tabOn]}
          >
            <Text style={[st.tabText, sort === t.key && st.tabTextOn]}>{t.label}</Text>
          </Pressable>
        ))}
      </View>

      {loading ? (
        <Text style={st.refreshing}>Refreshing the store…</Text>
      ) : offline ? (
        <Text style={st.refreshing}>Showing the bundled list — couldn't reach the store.</Text>
      ) : null}

      {list.length === 0 ? (
        <EmptyState
          title={loading ? "Loading the store…" : "No plugins match"}
          hint={loading ? "Fetching the registry." : "Try another search."}
        />
      ) : (
        list.map((p, i) => {
          const installed = !!installedMap[p.name];
          const pending = installedMap[p.name]?.status === "pending";
          return (
            <Card key={p.name} delay={i * 40}>
              <View style={st.top}>
                <View style={st.icon}>
                  <Text style={st.iconText}>{(p.name[0] || "?").toUpperCase()}</Text>
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={[typography.body, { color: colors.textPrimary, fontWeight: "700" }]}>
                    {p.name}
                    {p.tags.includes("featured") ? (
                      <Text style={{ color: colors.accentMemory }}>{"  ● featured"}</Text>
                    ) : null}
                  </Text>
                  <Text style={st.by}>
                    v{p.version} · {p.author}
                    {p.official ? <Text style={st.verified}>{"  ✓ Official"}</Text> : null}
                  </Text>
                </View>
              </View>

              <Text style={[typography.body, { color: colors.textSecondary, marginTop: space.sm }]}>
                {p.description}
              </Text>

              <View style={st.meta}>
                <Text style={st.metaText}>{p.downloads ? `↓ ${fmt(p.downloads)}` : "new"}</Text>
                <View style={st.stars}>
                  {[1, 2, 3, 4, 5].map((n) => (
                    <Pressable key={n} onPress={() => rate(p.name, n)} hitSlop={4}>
                      <Text
                        style={{
                          color: n <= Math.round(p.rating) ? colors.accentMemory : colors.statusPaused,
                          fontSize: 15,
                        }}
                      >
                        ★
                      </Text>
                    </Pressable>
                  ))}
                  <Text style={st.metaText}>{p.ratings_count ? ` ${p.rating.toFixed(1)}` : ""}</Text>
                </View>
              </View>

              <View style={st.chips}>
                {(p.requires.length ? p.requires.map((r) => `needs ${r}`) : ["no special access"]).map(
                  (c) => (
                    <View key={c} style={[st.chip, p.requires.length ? st.chipPerm : null]}>
                      <Text style={[st.chipText, p.requires.length ? st.chipTextPerm : null]}>{c}</Text>
                    </View>
                  ),
                )}
              </View>

              <View style={st.actions}>
                {installed ? (
                  <Pressable style={[st.btn, st.btnGhost]} onPress={() => onRemove(p)}>
                    <Text style={st.btnGhostText}>{pending ? "Pending · Remove" : "Remove"}</Text>
                  </Pressable>
                ) : (
                  <Pressable style={[st.btn, st.btnPrimary]} onPress={() => onInstall(p)}>
                    <Text style={st.btnPrimaryText}>Install</Text>
                  </Pressable>
                )}
                {p.homepage ? (
                  <Pressable style={[st.btn, st.btnGhost]} onPress={() => Linking.openURL(p.homepage!)}>
                    <Text style={st.btnGhostText}>Source</Text>
                  </Pressable>
                ) : null}
              </View>

              <Pressable onPress={() => setDetail(p)} hitSlop={6}>
                <Text style={st.more}>See what it does & a preview →</Text>
              </Pressable>
            </Card>
          );
        })
      )}

      <PluginDetail
        plugin={detail}
        installed={detail ? !!installedMap[detail.name] : false}
        onClose={() => setDetail(null)}
        onInstall={onInstall}
        onRemove={onRemove}
      />
    </Screen>
  );
}

/** The plugin's own detail page — screenshot + how-it-helps copy + the exact
 *  permissions it asks for. All of it travels with the plugin (the author ships
 *  `long`, `forwho`, and `screenshot` in the registry), so this renders their
 *  page, not one hardcoded here. */
function PluginDetail({
  plugin, installed, onClose, onInstall, onRemove,
}: {
  plugin: PluginEntry | null;
  installed: boolean;
  onClose: () => void;
  onInstall: (p: PluginEntry) => void;
  onRemove: (p: PluginEntry) => void;
}) {
  const p = plugin;
  const paras = p ? (p.long.length ? p.long : [p.description]) : [];
  return (
    <Modal visible={!!p} transparent animationType="slide" onRequestClose={onClose}>
      <View style={st.overlay}>
        <Pressable style={st.overlayBg} onPress={onClose} />
        {p ? (
          <View style={st.sheet}>
            <ScrollView showsVerticalScrollIndicator={false}>
              {p.screenshot ? (
                <Image source={{ uri: p.screenshot }} style={st.shot} resizeMode="cover" />
              ) : null}
              <View style={st.sheetBody}>
                <View style={st.sheetHead}>
                  <View style={{ flex: 1 }}>
                    <Text style={[typography.headline, { color: colors.textPrimary }]}>{p.name}</Text>
                    <Text style={st.by}>
                      v{p.version} · {p.author}
                      {p.official ? <Text style={st.verified}>{"  ✓ Official"}</Text> : null}
                    </Text>
                    {p.official ? (
                      <Text style={st.officialNote}>
                        Built and maintained by the DreamLayer team.
                      </Text>
                    ) : null}
                  </View>
                  <Pressable onPress={onClose} hitSlop={8} style={st.x}
                    accessibilityRole="button" accessibilityLabel="Close">
                    <Text style={{ color: colors.textPrimary, fontSize: 16 }}>✕</Text>
                  </Pressable>
                </View>

                {paras.map((t, i) => (
                  <Text key={i} style={st.long}>
                    {t}
                  </Text>
                ))}

                {p.forwho ? (
                  <>
                    <Text style={st.sec}>WHO IT’S FOR</Text>
                    <Text style={[typography.body, { color: colors.textSecondary }]}>{p.forwho}</Text>
                  </>
                ) : null}

                <Text style={st.sec}>PERMISSIONS IT ASKS FOR</Text>
                {p.requires.length ? (
                  p.requires.map((r) => (
                    <View key={r} style={st.permRow}>
                      <Text style={st.permName}>{r}</Text>
                      <Text style={st.permHelp}>{CAP_HELP[r] || "a capability it requested"}</Text>
                    </View>
                  ))
                ) : (
                  <Text style={[typography.body, { color: colors.textSecondary }]}>
                    No special access — it only extends the layer’s own surfaces.
                  </Text>
                )}

                <View style={st.meta}>
                  <Text style={st.metaText}>{p.downloads ? `↓ ${fmt(p.downloads)} installs` : "new"}</Text>
                  <Text style={st.metaText}>
                    {p.ratings_count ? `★ ${p.rating.toFixed(1)} (${p.ratings_count})` : "unrated"}
                  </Text>
                </View>

                <View style={st.actions}>
                  {installed ? (
                    <Pressable
                      style={[st.btn, st.btnGhost]}
                      onPress={() => {
                        onClose();
                        onRemove(p);
                      }}
                    >
                      <Text style={st.btnGhostText}>Remove</Text>
                    </Pressable>
                  ) : (
                    <Pressable
                      style={[st.btn, st.btnPrimary]}
                      onPress={() => {
                        onClose();
                        onInstall(p);
                      }}
                    >
                      <Text style={st.btnPrimaryText}>Install</Text>
                    </Pressable>
                  )}
                  {p.homepage ? (
                    <Pressable style={[st.btn, st.btnGhost]} onPress={() => Linking.openURL(p.homepage!)}>
                      <Text style={st.btnGhostText}>Source</Text>
                    </Pressable>
                  ) : null}
                </View>
              </View>
            </ScrollView>
          </View>
        ) : null}
      </View>
    </Modal>
  );
}

const st = StyleSheet.create({
  search: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    borderRadius: 999,
    color: colors.textPrimary,
    paddingHorizontal: space.lg,
    paddingVertical: space.md,
    marginBottom: space.md,
  },
  tabs: { flexDirection: "row", flexWrap: "wrap", gap: space.xs, marginBottom: space.md },
  tab: {
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    borderRadius: 999,
    paddingHorizontal: space.md,
    paddingVertical: space.xs,
  },
  tabOn: { backgroundColor: colors.accentMemory, borderColor: colors.accentMemory },
  tabText: { color: colors.textSecondary, fontSize: 12, letterSpacing: 0.6 },
  tabTextOn: { color: "#00201C", fontWeight: "700" },
  top: { flexDirection: "row", alignItems: "center", gap: space.md },
  icon: {
    width: 42,
    height: 42,
    borderRadius: 12,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "rgba(47,212,196,0.12)",
    borderWidth: 1,
    borderColor: "rgba(47,212,196,0.3)",
  },
  iconText: { color: colors.accentMemory, fontWeight: "800", fontSize: 18 },
  by: { color: colors.statusPaused, fontSize: 12, marginTop: 2, fontVariant: ["tabular-nums"] },
  verified: { color: colors.accentMemory, fontSize: 12, fontWeight: "700" },
  officialNote: { color: colors.textSecondary, fontSize: 11.5, marginTop: 2, fontStyle: "italic" },
  refreshing: { color: colors.textSecondary, fontSize: 12, marginBottom: space.sm },
  meta: { flexDirection: "row", alignItems: "center", gap: space.lg, marginTop: space.md },
  metaText: { color: colors.textSecondary, fontSize: 13 },
  stars: { flexDirection: "row", alignItems: "center", gap: 2 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: space.xs, marginTop: space.md },
  chip: {
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    borderRadius: 6,
    paddingHorizontal: space.sm,
    paddingVertical: 3,
  },
  chipPerm: { borderColor: "rgba(224,107,82,0.4)" },
  chipText: { color: colors.textSecondary, fontSize: 11, letterSpacing: 0.4 },
  chipTextPerm: { color: colors.accentAttention },
  actions: { flexDirection: "row", gap: space.sm, marginTop: space.lg },
  btn: { borderRadius: 999, paddingHorizontal: space.lg, paddingVertical: space.sm },
  btnPrimary: { backgroundColor: colors.accentMemory },
  btnPrimaryText: { color: "#00201C", fontWeight: "700" },
  btnGhost: { borderWidth: 1, borderColor: colors.borderSubtle },
  btnGhostText: { color: colors.textPrimary, fontWeight: "600" },
  more: { color: colors.accentMemory, fontSize: 12.5, fontWeight: "600", marginTop: space.md },
  // detail sheet
  overlay: { flex: 1, justifyContent: "flex-end" },
  // Inlined absolute-fill (RN minors ≥0.82 drop StyleSheet.absoluteFillObject
  // from the typings; the literal works on every RN version).
  overlayBg: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0, backgroundColor: "rgba(0,0,0,0.6)" },
  sheet: {
    maxHeight: "88%",
    backgroundColor: colors.surface,
    borderTopLeftRadius: 22,
    borderTopRightRadius: 22,
    borderWidth: 1,
    borderColor: colors.borderSubtle,
    overflow: "hidden",
  },
  shot: { width: "100%", aspectRatio: 640 / 340, backgroundColor: colors.background },
  sheetBody: { padding: space.lg },
  sheetHead: { flexDirection: "row", alignItems: "flex-start", marginBottom: space.md },
  x: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: colors.borderSubtle,
  },
  long: { color: colors.textSecondary, fontSize: 15, lineHeight: 23, marginBottom: space.sm },
  sec: {
    color: colors.accentMemory,
    fontSize: 11,
    letterSpacing: 1.6,
    marginTop: space.lg,
    marginBottom: space.xs,
  },
  permRow: { flexDirection: "row", alignItems: "flex-start", gap: space.md, marginTop: space.xs },
  permName: {
    color: colors.accentAttention,
    fontSize: 11.5,
    letterSpacing: 0.4,
    minWidth: 68,
    textTransform: "uppercase",
    fontWeight: "700",
  },
  permHelp: { color: colors.textSecondary, fontSize: 14, flex: 1 },
});
