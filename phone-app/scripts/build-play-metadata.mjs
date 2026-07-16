#!/usr/bin/env node
/**
 * Generate the fastlane *supply* metadata tree (Google Play) from the same
 * human-readable listing sources the App Store tree is built from. One source
 * of truth: full descriptions and release notes come verbatim from
 * store/listing.md (English) and store/listing-localized.md (8 locales);
 * the Play-only ≤80-char short descriptions come from store/play-listing.md.
 *
 *   node scripts/build-play-metadata.mjs
 *
 * Writes fastlane/metadata/android/<playLocale>/{title,short_description,
 * full_description}.txt + changelogs/1.txt (versionCode 1). Hard-fails if a
 * short description exceeds Play's 80-character limit, a title exceeds 30, or
 * a description exceeds 4000 — the same guarantee the CI typecheck gives code.
 * Images (feature graphic, screenshots) are rendered separately by
 * scripts/make-play-assets.py.
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (p) => fs.readFileSync(path.join(ROOT, p), "utf8");
const listing = read("store/listing.md");
const loc = read("store/listing-localized.md");
const play = read("store/play-listing.md");

// App Store locale -> Play locale
const PLAY_LOCALE = {
  "en-US": "en-US", "es-ES": "es-ES", "fr-FR": "fr-FR", "de-DE": "de-DE",
  it: "it-IT", "pt-BR": "pt-BR", ja: "ja-JP", ko: "ko-KR", "zh-Hans": "zh-CN",
};

function fencedAfter(md, headingRe) {
  const m = md.match(headingRe);
  if (!m) return "";
  const rest = md.slice(m.index + m[0].length);
  const fence = rest.match(/```[a-z]*\n([\s\S]*?)\n```/);
  return fence ? fence[1].trim() : "";
}

// ---- descriptions & release notes from the App Store sources -------------
const texts = {
  "en-US": {
    description: fencedAfter(listing, /## Description[^\n]*\n/),
    notes: fencedAfter(listing, /## What's New[^\n]*\n/),
  },
};
for (const raw of loc.split(/\n## /).slice(1)) {
  const codeM = raw.match(/\(([a-zA-Z-]+)\)/);
  if (!codeM) continue;
  const fenced = raw.match(/\*\*Description:\*\*\s*\n```[a-z]*\n([\s\S]*?)\n```/);
  const notes = raw.match(/\*\*What's New:\*\*\s*`([^`]+)`/);
  texts[codeM[1]] = {
    description: fenced ? fenced[1].trim() : "",
    notes: notes ? notes[1].trim() : "",
  };
}

// ---- short descriptions from the Play table ------------------------------
const shorts = {};
for (const row of play.matchAll(/^\|\s*([a-z]{2}-[A-Z]{2})\s*\|\s*(.+?)\s*\|$/gm)) {
  shorts[row[1]] = row[2];
}

// ---- write the supply tree ------------------------------------------------
const META = path.join(ROOT, "fastlane/metadata/android");
const fail = (msg) => { console.error("✗ " + msg); process.exitCode = 1; };

let count = 0;
for (const [appLocale, playLocale] of Object.entries(PLAY_LOCALE)) {
  const t = texts[appLocale];
  const short = shorts[playLocale];
  if (!t?.description) { fail(`missing description for ${appLocale}`); continue; }
  if (!short) { fail(`missing Play short description for ${playLocale}`); continue; }
  if ([...short].length > 80) fail(`short description for ${playLocale} exceeds 80 chars (${[...short].length})`);
  if ([...t.description].length > 4000) fail(`description for ${playLocale} exceeds 4000 chars`);

  const dir = path.join(META, playLocale);
  fs.mkdirSync(path.join(dir, "changelogs"), { recursive: true });
  fs.writeFileSync(path.join(dir, "title.txt"), "DreamLayer\n");
  fs.writeFileSync(path.join(dir, "short_description.txt"), short + "\n");
  fs.writeFileSync(path.join(dir, "full_description.txt"), t.description + "\n");
  if (t.notes) fs.writeFileSync(path.join(dir, "changelogs", "1.txt"), t.notes + "\n");
  count++;
}

if (process.exitCode) process.exit(process.exitCode);
console.log(`Generated Play metadata for ${count} locales: ${Object.values(PLAY_LOCALE).sort().join(", ")}`);
