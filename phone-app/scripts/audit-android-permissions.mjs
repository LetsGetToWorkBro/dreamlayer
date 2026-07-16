#!/usr/bin/env node
/**
 * Android permission audit — the privacy contract, enforced by CI.
 *
 * DreamLayer's posture is the product: the merged Android manifest may carry
 * exactly the permissions below and nothing else. Libraries love to sneak
 * permissions in through their own manifests at gradle merge time, so this
 * audits BOTH sources of truth:
 *
 *   1. the app manifest that `expo prebuild --platform android` generates
 *      (run prebuild first — CI does), honoring tools:node="remove" entries
 *      (app.json android.blockedPermissions), and
 *   2. every library manifest under node_modules/ that gradle would merge
 *      (android/src/main/AndroidManifest.xml), minus the blocked ones.
 *
 * Also pins the networking stance: android:networkSecurityConfig must be
 * wired and the blanket android:usesCleartextTraffic flag must never appear
 * (see plugins/withAndroidLanCleartext.js for why).
 *
 *   npx expo prebuild --platform android --no-install
 *   node scripts/audit-android-permissions.mjs
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

/** The contract. Every entry has a reason; add nothing without one. */
const ALLOWED = new Set([
  "android.permission.CAMERA",               // QR pairing scan, on-device only
  "android.permission.INTERNET",             // phone<->Brain (LAN), opt-in relay/cloud
  "android.permission.ACCESS_NETWORK_STATE", // expo-image/Glide connectivity retries
  "android.permission.MODIFY_AUDIO_SETTINGS",// expo-audio focus (earcons duck music)
  "android.permission.VIBRATE",              // the haptic vocabulary
  "android.permission.POST_NOTIFICATIONS",   // brief/message mirrors, runtime-gated
]);

const failures = [];
const fail = (msg) => failures.push(msg);

// ---- 1. the generated app manifest ----------------------------------------
const appManifestPath = path.join(ROOT, "android/app/src/main/AndroidManifest.xml");
if (!fs.existsSync(appManifestPath)) {
  console.error("✗ android/app/src/main/AndroidManifest.xml not found — run `npx expo prebuild --platform android --no-install` first");
  process.exit(2);
}
const appManifest = fs.readFileSync(appManifestPath, "utf8");

const blocked = new Set();
const appDeclared = new Set();
for (const m of appManifest.matchAll(/<uses-permission[^>]*android:name="([^"]+)"[^>]*\/?>/g)) {
  if (/tools:node="remove"/.test(m[0])) blocked.add(m[1]);
  else appDeclared.add(m[1]);
}
for (const p of appDeclared) {
  if (!ALLOWED.has(p)) fail(`app manifest declares un-allowlisted permission: ${p}`);
}

// ---- 2. every library manifest gradle would merge --------------------------
function packageDirs() {
  const nm = path.join(ROOT, "node_modules");
  const out = [];
  for (const entry of fs.readdirSync(nm)) {
    if (entry.startsWith(".")) continue;
    if (entry.startsWith("@")) {
      for (const sub of fs.readdirSync(path.join(nm, entry))) out.push(path.join(nm, entry, sub));
    } else out.push(path.join(nm, entry));
  }
  return out;
}

const libDeclared = new Map(); // permission -> [packages]
for (const dir of packageDirs()) {
  for (const rel of ["android/src/main/AndroidManifest.xml", "android/AndroidManifest.xml"]) {
    const p = path.join(dir, rel);
    if (!fs.existsSync(p)) continue;
    const xml = fs.readFileSync(p, "utf8");
    for (const m of xml.matchAll(/<uses-permission[^>]*android:name="([^"]+)"[^>]*\/?>/g)) {
      const perm = m[1];
      if (!libDeclared.has(perm)) libDeclared.set(perm, []);
      libDeclared.get(perm).push(path.relative(path.join(ROOT, "node_modules"), dir));
    }
  }
}
for (const [perm, pkgs] of libDeclared) {
  if (!ALLOWED.has(perm) && !blocked.has(perm)) {
    fail(`library manifest adds un-allowlisted permission ${perm} (from ${[...new Set(pkgs)].join(", ")}) — allowlist it here with a reason, or block it in app.json android.blockedPermissions`);
  }
}

// ---- 3. the networking stance ----------------------------------------------
if (!/android:networkSecurityConfig="@xml\/network_security_config"/.test(appManifest)) {
  fail("application is missing android:networkSecurityConfig — the LAN cleartext policy is unwired (plugins/withAndroidLanCleartext.js)");
}
if (/android:usesCleartextTraffic/.test(appManifest)) {
  fail("android:usesCleartextTraffic appeared in the manifest — the blanket flag is forbidden; the scoped policy lives in network_security_config.xml");
}
if (!/android:allowBackup="false"/.test(appManifest)) {
  fail('allowBackup must stay "false" — cloud backup would carry the Brain token and caches');
}

// ---- verdict ----------------------------------------------------------------
if (failures.length) {
  for (const f of failures) console.error("✗ " + f);
  process.exit(1);
}
console.log(`✓ merged-manifest permission set is exactly the contract (${ALLOWED.size} allowed, ${blocked.size} explicitly blocked)`);
console.log("✓ networkSecurityConfig wired, no blanket cleartext flag, backups off");
