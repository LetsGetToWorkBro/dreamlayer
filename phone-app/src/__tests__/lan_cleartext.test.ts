/** The cleartext policy — the app half of Android's network security config.
 * Android XML can't scope cleartext to private IP ranges, so this range check
 * IS the enforcement (see plugins/withAndroidLanCleartext.js). Pin the ranges
 * and the places a URL can enter the app: the pairing code and hydration. */
import { cleartextAllowed, isPrivateLanHost, encodePairing } from "../services/pairing";
import { useBrainStore } from "../state/useBrainStore";

describe("isPrivateLanHost — the range table", () => {
  const yes = [
    "192.168.1.20", "10.0.0.9", "10.255.255.255", "172.16.0.1", "172.31.255.255",
    "127.0.0.1", "169.254.10.10",           // loopback + link-local
    "100.64.0.1", "100.127.255.255",         // CGNAT — Tailscale addresses
    "localhost", "mac.local", "brain.home.arpa",
    "mac",                                    // dotless = LAN search-domain name
    "::1", "fd12:3456::1", "fc00::1", "fe80::1", "[::1]",
  ];
  const no = [
    "8.8.8.8", "1.1.1.1", "172.15.0.1", "172.32.0.1",  // just outside 172.16/12
    "100.63.255.255", "100.128.0.1",                    // just outside CGNAT
    "192.169.0.1", "11.0.0.1", "999.1.1.1",
    "example.com", "brain.example.com", "local.evil.com",
    "2600:1901::1", "",
    // IP literals in disguise: a native resolver decodes these to PUBLIC hosts,
    // so the classifier must NOT wave them through as "dotless LAN name" or a
    // decimal-parsed private range (refute 2026-07-18).
    "134744072",            // 32-bit decimal for 8.8.8.8 (dotless, all digits)
    "3627734734",           // 32-bit decimal for a public IP
    "2130706433",           // 32-bit decimal for 127.0.0.1 — non-canonical, refuse
    "0x8080808",            // hex integer literal
    "0xdeadbeef",           // hex integer literal
    "010.0.0.1",            // leading-zero octet → octal 8.0.0.1 to inet_aton
    "0177.0.0.1",           // leading-zero octet → octal 127 (loopback) ambiguity
    "192.168.010.1",        // leading-zero octet inside an otherwise-private quad
  ];
  it.each(yes)("allows %s", (h) => expect(isPrivateLanHost(h)).toBe(true));
  it.each(no)("refuses %s", (h) => expect(isPrivateLanHost(h)).toBe(false));
});

describe("cleartextAllowed — the URL gate", () => {
  it("lets HTTPS go anywhere", () => {
    expect(cleartextAllowed("https://relay.example.com")).toBe(true);
    expect(cleartextAllowed("https://8.8.8.8/x")).toBe(true);
  });
  it("lets plain HTTP reach only the owner's network", () => {
    expect(cleartextAllowed("http://192.168.1.20:7777")).toBe(true);
    expect(cleartextAllowed("http://mac.local:7777/dreamlayer")).toBe(true);
    expect(cleartextAllowed("http://[::1]:7777")).toBe(true);
    expect(cleartextAllowed("http://example.com:7777")).toBe(false);
    expect(cleartextAllowed("http://8.8.8.8:7777")).toBe(false);
  });
  it("is not fooled by userinfo spoofing the host", () => {
    expect(cleartextAllowed("http://192.168.1.20@evil.com/")).toBe(false);
    expect(cleartextAllowed("http://evil.com@192.168.1.20:7777")).toBe(true);
  });
  it("refuses integer/octal IP literals that decode to public hosts", () => {
    expect(cleartextAllowed("http://134744072:7777")).toBe(false);      // = 8.8.8.8
    expect(cleartextAllowed("http://0x8080808/x")).toBe(false);         // hex public
    expect(cleartextAllowed("http://010.0.0.1:7777")).toBe(false);      // octal octet
    // userinfo strip must not leave a public integer host looking private
    expect(cleartextAllowed("http://evil.com@134744072:7777")).toBe(false);
  });
  it("refuses anything unparseable or non-http(s)", () => {
    expect(cleartextAllowed("")).toBe(false);
    expect(cleartextAllowed("not a url")).toBe(false);
    expect(cleartextAllowed("ftp://192.168.1.20")).toBe(false);
  });
});

describe("the gate at the doors: pairing and hydration", () => {
  const unpaired = { connected: false, url: "", token: "", relayUrl: "" };
  beforeAll(() => {
    // pairFromCode pushes config to the (fake) Brain — never let jest hit the wire
    (global as { fetch?: unknown }).fetch = jest.fn(() => Promise.reject(new Error("offline test")));
  });
  beforeEach(() => {
    useBrainStore.setState({ macMini: { ...unpaired }, demoMode: false } as never);
  });

  it("refuses to pair a public cleartext Brain URL", () => {
    const code = encodePairing({
      brainUrl: "http://brain.example.com:7777", token: "t", glassesId: "", label: "DreamLayer", relayUrl: "",
    });
    const res = useBrainStore.getState().pairFromCode(code);
    expect(res.brain).toBe(false);
    expect(useBrainStore.getState().macMini.url).toBe("");
  });

  it("pairs a LAN Brain but drops a public cleartext relay", () => {
    const code = encodePairing({
      brainUrl: "http://192.168.1.20:7777", token: "t", glassesId: "", label: "DreamLayer",
      relayUrl: "http://relay.example.com",
    });
    const res = useBrainStore.getState().pairFromCode(code);
    expect(res.brain).toBe(true);
    expect(useBrainStore.getState().macMini.url).toBe("http://192.168.1.20:7777");
    expect(useBrainStore.getState().macMini.relayUrl).toBe("");
  });

  it("keeps an HTTPS relay untouched", () => {
    const code = encodePairing({
      brainUrl: "http://192.168.1.20:7777", token: "t", glassesId: "", label: "DreamLayer",
      relayUrl: "https://relay.example.com",
    });
    useBrainStore.getState().pairFromCode(code);
    expect(useBrainStore.getState().macMini.relayUrl).toBe("https://relay.example.com");
  });

  it("hydration drops a persisted pairing that violates the policy", async () => {
    const AsyncStorage = require("@react-native-async-storage/async-storage").default;
    await AsyncStorage.setItem(
      "dreamlayer.brain.v1",
      JSON.stringify({ macMini: { connected: true, url: "http://brain.example.com:7777", token: "t" } })
    );
    useBrainStore.setState({ hydrated: false } as never);
    await useBrainStore.getState().hydrate();
    expect(useBrainStore.getState().macMini.url).toBe("");
    expect(useBrainStore.getState().macMini.connected).toBe(false);
  });
});
