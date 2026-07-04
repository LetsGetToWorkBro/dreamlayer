import React from "react";
import {
  View, Text, StyleSheet, ScrollView, TextInput, Pressable, Alert, Linking,
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

/**
 * The Plugins screen — browse the git-backed registry and manage what your
 * layer runs. Installing grants a plugin the capabilities it asks for and tells
 * the paired hub to fetch + validate + run it; the phone never runs plugin code
 * itself (docs/MARKETPLACE.md).
 */
export default function Plugins() {
  const index = usePluginStore((s) => s.index);
  const loading = usePluginStore((s) => s.loading);
  const installedMap = usePluginStore((s) => s.installed);
  const searchFn = usePluginStore((s) => s.search);
  const hydrate = usePluginStore((s) => s.hydrate);
  const install = usePluginStore((s) => s.install);
  const remove = usePluginStore((s) => s.remove);
  const mac = useBrainStore((s) => s.macMini);

  const [query, setQuery] = React.useState("");
  const [sort, setSort] = React.useState<Sort>("featured");

  React.useEffect(() => {
    hydrate();
  }, [hydrate]);

  const list = searchFn(query, sort as SortKey);
  const macTarget = mac.connected ? { url: mac.url, token: mac.token } : null;

  const onInstall = (p: PluginEntry) => {
    const perms = p.requires.length ? p.requires.join(", ") : "no special access";
    Alert.alert(
      `Install ${p.name}?`,
      `This plugin will be able to use: ${perms}.\n\n` +
        (macTarget
          ? "It's validated on your Mac (integrity + capability scan + smoke test) before it runs."
          : "Queued — it installs and is validated on your hub the next time one is paired."),
      [
        { text: "Cancel", style: "cancel" },
        { text: "Install", onPress: () => install(p, macTarget) },
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
                  </Text>
                </View>
              </View>

              <Text style={[typography.body, { color: colors.textSecondary, marginTop: space.sm }]}>
                {p.description}
              </Text>

              <View style={st.meta}>
                <Text style={st.metaText}>{p.downloads ? `↓ ${fmt(p.downloads)}` : "new"}</Text>
                <Text style={st.metaText}>
                  {p.ratings_count ? `★ ${p.rating.toFixed(1)}` : "unrated"}
                </Text>
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
            </Card>
          );
        })
      )}
    </Screen>
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
  meta: { flexDirection: "row", gap: space.lg, marginTop: space.md },
  metaText: { color: colors.textSecondary, fontSize: 13 },
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
});
