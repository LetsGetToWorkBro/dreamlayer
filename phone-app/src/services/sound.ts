/**
 * sound.ts — play Oracle's short earcons on the phone (expo-audio).
 *
 * The "Listen!" chime is *your* sound: drop an audio file at
 * `assets/sounds/hark.(mp3|wav|m4a)` and it plays whenever Oracle taps you on
 * the shoulder. Everything is loaded lazily and fully guarded, so a missing
 * module or a missing file is a silent no-op (web, tests, or before you've
 * added a clip) — the sound is polish, never a dependency.
 *
 * Bundlers need static require() for assets, so the clip map is explicit. Add a
 * file and uncomment its line; until then playing an earcon simply does nothing.
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

// Earcon id → bundled asset. Drop the file, then uncomment its require().
const CLIPS: Record<string, number | null> = {
  // hark: require("../../assets/sounds/hark.mp3"),
  hark: null,
  wake: null,
  success: null,
};

/**
 * Play a named earcon. No-ops if expo-audio is unavailable or no clip is
 * registered for the id. Fire-and-forget; never throws.
 */
export async function playEarcon(name: string): Promise<void> {
  const clip = CLIPS[name];
  if (clip == null) return; // no sound registered yet — silent
  const A = mod();
  if (!A?.createAudioPlayer) return;
  try {
    const player = A.createAudioPlayer(clip);
    player.play();
    // release shortly after it finishes so we don't leak players
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

/** Oracle's "Listen!" — the shoulder tap. */
export function playListen(): void {
  playEarcon("hark");
}
