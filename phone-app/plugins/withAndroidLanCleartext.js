/**
 * withAndroidLanCleartext — lets the phone speak plain HTTP to the Brain on
 * the local network, and documents exactly how far that trust extends.
 *
 * WHY THIS EXISTS
 * The phone talks to a self-hosted Brain over the owner's LAN
 * (http://<lan-ip>:7777 with an X-DreamLayer-Token header — see
 * src/state/useBrainStore.ts). Android 9+ blocks all cleartext HTTP by
 * default, which would break QR pairing, status polling, and every ask
 * round-trip on Android; this plugin is the Android half of the fix.
 *
 * iOS needs the SAME unblock — App Transport Security also refuses cleartext
 * http:// (including to private/`.local`/IP-literal hosts) unless told
 * otherwise. That half lives in app.json (ios.infoPlist): NSAllowsLocalNetworking
 * exempts local resources from ATS without opening arbitrary cleartext, and
 * NSLocalNetworkUsageDescription covers the iOS 14+ local-network permission
 * for the direct LAN connection. Guarded by src/__tests__/ios_ats_lan.test.ts.
 *
 * WHY IT IS SHAPED THIS WAY
 * The honest goal is "cleartext to private-range/LAN addresses only."
 * Android's network security config cannot express that directly: <domain>
 * entries match literal hostnames/IPs, not CIDR ranges, so RFC 1918 space
 * (10/8, 172.16/12, 192.168/16) cannot be enumerated in XML. Instead the
 * scoping is enforced in TWO layers:
 *
 *   1. This network security config permits cleartext at the base so a
 *      pairing QR carrying any private LAN IP works. We deliberately do NOT
 *      set android:usesCleartextTraffic="true" — that manifest flag is a
 *      blunt, undocumented-in-one-place blanket; the XML below is the single
 *      commented home for this policy, and CI fails if the flag ever appears
 *      (scripts/audit-android-permissions.mjs).
 *
 *   2. The app itself refuses to *use* a cleartext URL outside private
 *      space: src/services/pairing.ts#cleartextAllowed() rejects any
 *      http:// Brain/relay URL whose host is not loopback, RFC 1918,
 *      link-local, CGNAT (Tailscale), or .local/.home.arpa — enforced at
 *      pairing time and again before every fetch in useBrainStore. Unit
 *      tests pin the ranges (src/__tests__/lan_cleartext.test.ts).
 *
 * Net effect: the only cleartext the app will ever emit is phone→Brain on
 * the owner's own network — the existing, documented privacy posture
 * (landing/privacy.html: "traffic is between your own devices, not to us").
 */
const { withAndroidManifest, withDangerousMod } = require("expo/config-plugins");
const fs = require("fs");
const path = require("path");

const NETWORK_SECURITY_CONFIG = `<?xml version="1.0" encoding="utf-8"?>
<!--
  DreamLayer network security config.

  Cleartext HTTP exists ONLY for the phone <-> Brain link on the owner's LAN
  (the Brain is self-hosted at http://<private-ip>:7777). Android cannot
  scope cleartext to RFC 1918 ranges in this file (domain rules are literal
  hostnames/IPs, no CIDR), so the range check lives in the app instead:
  src/services/pairing.ts#cleartextAllowed() refuses any http:// URL whose
  host is not private/loopback/.local, at pairing time and before every
  fetch. Keep the two files in sync; see plugins/withAndroidLanCleartext.js
  for the full rationale.

  No debug-overrides, no custom trust anchors: HTTPS traffic (the opt-in
  relay, opt-in cloud AI) keeps the platform's default certificate trust.
-->
<network-security-config>
  <base-config cleartextTrafficPermitted="true">
    <trust-anchors>
      <certificates src="system" />
    </trust-anchors>
  </base-config>
</network-security-config>
`;

function withLanCleartext(config) {
  // 1. drop the res/xml file into the native project at prebuild time
  config = withDangerousMod(config, [
    "android",
    async (cfg) => {
      const resXml = path.join(cfg.modRequest.platformProjectRoot, "app/src/main/res/xml");
      fs.mkdirSync(resXml, { recursive: true });
      fs.writeFileSync(path.join(resXml, "network_security_config.xml"), NETWORK_SECURITY_CONFIG);
      return cfg;
    },
  ]);
  // 2. point the <application> at it
  return withAndroidManifest(config, (cfg) => {
    const app = cfg.modResults.manifest.application?.[0];
    if (app) {
      app.$["android:networkSecurityConfig"] = "@xml/network_security_config";
      // never the blanket manifest flag — the XML above is the one documented home
      delete app.$["android:usesCleartextTraffic"];
    }
    return cfg;
  });
}

module.exports = withLanCleartext;
