#!/usr/bin/env node
/**
 * Generate the fastlane deliver metadata tree from the human-readable listing
 * sources. Single source of truth: store/listing.md (English), store/
 * listing-localized.md (8 locales), store/review-notes.txt.
 *
 *   node scripts/build-appstore-metadata.mjs
 *
 * Writes fastlane/metadata/<locale>/*.txt for name, subtitle, keywords,
 * description, promotional_text, release_notes, plus marketing/support/privacy
 * URLs, app-level copyright/categories, and review_information/notes.txt.
 * Screenshots are managed separately in fastlane/screenshots/<locale>/.
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (p) => fs.readFileSync(path.join(ROOT, p), "utf8");
const listing = read("store/listing.md");
const loc = read("store/listing-localized.md");

function afterHeading(md, headingRe) {
  const m = md.match(headingRe);
  if (!m) return "";
  const rest = md.slice(m.index + m[0].length);
  const fence = rest.match(/```[a-z]*\n([\s\S]*?)\n```/);
  return fence ? fence[1].trim() : "";
}

const en = {
  name: afterHeading(listing, /## App Name[^\n]*\n/),
  subtitle: afterHeading(listing, /## Subtitle[^\n]*\n/),
  keywords: afterHeading(listing, /## Keywords[^\n]*\n/),
  promotional_text: afterHeading(listing, /## Promotional text[^\n]*\n/),
  description: afterHeading(listing, /## Description[^\n]*\n/),
  release_notes: afterHeading(listing, /## What's New[^\n]*\n/),
};

const blocks = loc.split(/\n## /).slice(1);
const locales = {};
for (const raw of blocks) {
  const codeM = raw.match(/\(([a-zA-Z-]+)\)/);
  if (!codeM) continue;
  const code = codeM[1];
  const inline = (label) => {
    const m = raw.match(new RegExp("\\*\\*" + label + ":\\*\\*\\s*`([^`]+)`"));
    return m ? m[1].trim() : "";
  };
  const fenced = (label) => {
    const m = raw.match(new RegExp("\\*\\*" + label + ":\\*\\*\\s*\\n```[a-z]*\\n([\\s\\S]*?)\\n```"));
    return m ? m[1].trim() : "";
  };
  locales[code] = {
    name: "DreamLayer",
    subtitle: inline("Subtitle"),
    keywords: inline("Keywords"),
    promotional_text: fenced("Promotional text"),
    description: fenced("Description"),
    release_notes: inline("What's New"),
  };
}
locales["en-US"] = en;

const META = path.join(ROOT, "fastlane/metadata");
fs.mkdirSync(META, { recursive: true });
const FIELDS = ["name", "subtitle", "keywords", "promotional_text", "description", "release_notes"];
for (const [code, d] of Object.entries(locales)) {
  const dir = path.join(META, code);
  fs.mkdirSync(dir, { recursive: true });
  for (const f of FIELDS) if (d[f]) fs.writeFileSync(path.join(dir, `${f}.txt`), d[f] + "\n");
  fs.writeFileSync(path.join(dir, "marketing_url.txt"), "https://dreamlayer.app\n");
  fs.writeFileSync(path.join(dir, "support_url.txt"), "https://dreamlayer.app\n");
  fs.writeFileSync(path.join(dir, "privacy_url.txt"), "https://dreamlayer.app/privacy.html\n");
}
fs.writeFileSync(path.join(META, "copyright.txt"), "2026 DreamLayer\n");
fs.writeFileSync(path.join(META, "primary_category.txt"), "PRODUCTIVITY\n");
fs.writeFileSync(path.join(META, "secondary_category.txt"), "LIFESTYLE\n");

const RI = path.join(META, "review_information");
fs.mkdirSync(RI, { recursive: true });
fs.writeFileSync(path.join(RI, "notes.txt"), read("store/review-notes.txt"));
for (const [f, v] of [["demo_user", ""], ["demo_password", ""], ["email_address", "info@labyrinth.vision"],
  ["first_name", ""], ["last_name", ""], ["phone_number", ""]])
  fs.writeFileSync(path.join(RI, `${f}.txt`), v + "\n");

console.log(`Generated metadata for: ${Object.keys(locales).sort().join(", ")}`);
