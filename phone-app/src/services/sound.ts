/**
 * sound.ts — Juno's voice: short earcons, with variety.
 *
 * Each cue is a *family* of clips (Hey 1/2, Listen 1/2, …). When Juno wants
 * your attention we pick a variant at random, never repeating the last one, so
 * you don't hear the exact same thing every time. Card `earcon` ids map onto a
 * family; the runtime just says "play the listen cue" and we vary it.
 *
 * expo-audio is loaded lazily and everything is guarded, so a missing module
 * (web/tests) is a silent no-op. Metro needs static require()s, so variants are
 * listed explicitly — add a file, drop its require() in the right family.
 */
let Audio: any = null;
let tried = false;

function mod(): any {
  if (!tried) {
    tried = true;
    try {
      Audio = require("expo-audio");
    } catch {
      Audio = null;
    }
  }
  return Audio;
}

// A cue family → its variant clips. Add more as you record them.
const FAMILIES: Record<string, number[]> = {
  hey: [
    require("../../assets/sounds/hey1.mp3"),
    require("../../assets/sounds/hey2.mp3"),
  ], // Juno wakes ("Hey Juno")
  listen: [
    require("../../assets/sounds/listen1.mp3"),
    require("../../assets/sounds/listen2.mp3"),
  ], // the "Listen!" tap
  look: [
    require("../../assets/sounds/look1.mp3"),
    require("../../assets/sounds/look2.mp3"),
  ], // "look at this"
  watchout: [
    require("../../assets/sounds/watchout1.mp3"),
    require("../../assets/sounds/watchout2.mp3"),
  ], // urgent heads-up
  sfx: [
    require("../../assets/sounds/sfx10.mp3"),
    require("../../assets/sounds/sfx13.mp3"),
  ],
};

// Card `earcon` ids → cue family.
const EARCON_FAMILY: Record<string, string> = {
  wake: "hey",
  hark: "listen",
  hark_urgent: "watchout",
  look: "look",
  chime: "sfx",
  hey: "hey",
  listen: "listen",
  watchout: "watchout",
};

const lastIdx: Record<string, number> = {};

function pick(family: string): number | null {
  let clips = FAMILIES[family] ?? [];
  if (clips.length === 0 && family === "watchout") clips = FAMILIES.listen ?? []; // fallback
  if (clips.length === 0) return null;
  if (clips.length === 1) return clips[0] ?? null;
  let i = Math.floor(Math.random() * clips.length);
  if (i === lastIdx[family]) i = (i + 1) % clips.length; // never repeat back-to-back
  lastIdx[family] = i;
  return clips[i] ?? null;
}

/** Play a cue by earcon id or family name. Varies the variant; never throws. */
export async function playEarcon(name: string): Promise<void> {
  const family = EARCON_FAMILY[name] ?? name;
  const clip = pick(family);
  if (clip == null) return;
  const A = mod();
  if (!A?.createAudioPlayer) return;
  try {
    const player = A.createAudioPlayer(clip);
    player.play();
    setTimeout(() => {
      try {
        player.remove();
      } catch {
        /* ignore */
      }
    }, 4000);
  } catch {
    /* audio unavailable — ignore */
  }
}

/** Juno's "Listen!" — the shoulder tap (Listen 1/2, rotated). */
export function playListen(): void {
  playEarcon("listen");
}
