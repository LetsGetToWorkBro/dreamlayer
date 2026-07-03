"""demo/catalog.py — every glasses feature, demo-ready.

One entry per HUD feature, mapped to its *real* card. From it we generate two
things automatically, so you can pick either format:

  • a short clip **per feature** (feature_scenes) — drop the one you're pitching;
  • one **master film** (master_scene) that walks the whole product in order.

Plus `write_catalog_md` emits the narration script — every feature, its card,
and a one-line VO — so the film and the voiceover stay in lockstep. The cards are
always the actual renderer output; this only sequences and labels them.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..hud.cards import ALL_SAMPLES
from .scene import Scene, Beat


@dataclass
class Feature:
    id: str
    title: str          # the on-screen / VO name
    blurb: str          # one line — the promise
    card: str           # an ALL_SAMPLES key
    group: str          # section in the master film


# ordered as a demo would walk it: wake → converse → perceive → remember → trust → protect
FEATURES: list[Feature] = [
    Feature("wake",        "Wake → your day",       "Put the Halo on; the morning brief is already waiting.",           "morning_brief",   "The morning"),
    Feature("oracle_wake", "Hey Oracle",            "A word wakes it — then just keep talking.",                        "listening",       "The morning"),
    Feature("oracle_do",   "Ask it anything",       "It runs the device or answers from your brain, in its own voice.", "oracle_reply",    "The morning"),

    Feature("captions",    "Live captions",         "Every word, transcribed at the rim.",                              "spoken_caption",  "In conversation"),
    Feature("dossier",     "Look → who is this",    "A glance names them and surfaces your history together.",           "person_dossier",  "In conversation"),
    Feature("rim_faces",   "Faces at the rim",      "Who they are, without staring.",                                   "person_context",  "In conversation"),
    Feature("answer_ahead","The answer before you speak", "It overhears a question and hands you the answer in time.",  "answer_ahead",    "In conversation"),
    Feature("veritas",     "Truth, checked live",   "Flags a claim that doesn't hold up — or contradicts what they told you before.", "fact_check", "In conversation"),
    Feature("truth_gauge", "Read the room",         "Delivery signals fused into one credibility read.",                "truth_gauge",     "In conversation"),
    Feature("hark",        "A tap on the shoulder", "Listen! — the one thing worth hearing, right now.",                "hark",            "In conversation"),

    Feature("commitment",  "What you owe",          "A promise you made, captured and returned when it matters.",        "commitment_recall","Memory"),
    Feature("drift",       "Before it slips",       "A commitment about to lapse, surfaced early.",                     "commitment_drift","Memory"),
    Feature("object",      "Where you left it",     "Your keys — last seen on the kitchen table, 7:42.",                "object_recall",   "Memory"),
    Feature("proactive",   "It remembers for you",  "The context you need, unasked.",                                   "proactive_memory","Memory"),
    Feature("saved",       "Keep a moment",         "Save what matters in a blink.",                                    "saved_memory",    "Memory"),
    Feature("anchor",      "Notes on the world",    "Leave a memory pinned to a place.",                                "world_anchor",    "Memory"),
    Feature("rewind",      "Rewind your day",       "Scrub the day in place, node by node.",                            "time_scrub_node", "Memory"),

    Feature("deviation",   "Off your usual path",   "A gentle nudge when something's unusual.",                         "deviation_alert", "Looking out for you"),
    Feature("inner",       "Your inner weather",    "Your own climate, made visible.",                                  "synesthesia",     "Looking out for you"),

    Feature("veil",        "Privacy Veil",          "One gesture and capture stops. Nothing kept.",                     "privacy_veil",    "Yours alone"),
    Feature("zone",        "Private zones",         "Places that never record.",                                        "private_zone",    "Yours alone"),
    Feature("consent",     "Ask first",             "Consent before anyone is captured.",                               "consent_required","Yours alone"),
    Feature("forget",      "Forget that",           "Undo the last capture instantly.",                                 "forget_last",     "Yours alone"),
    Feature("ready",       "Always ready",          "Calm until you need it.",                                          "ready",           "Yours alone"),
]


def _card(f: Feature) -> dict:
    return ALL_SAMPLES[f.card]


def feature_scenes(size=(1080, 1920), hold: float = 4.0) -> dict:
    """A short standalone clip per feature — the card, eased in and held."""
    out = {}
    for f in FEATURES:
        out[f.id] = Scene(f.id, size=size, beats=[
            Beat(_card(f), 0.4, 0.4 + hold, anchor=(0.5, 0.44),
                 width=0.54, label=f.title)],
            note=f"{f.title} — {f.blurb}")
    return out


def master_scene(size=(1080, 1920), per: float = 3.2, gap: float = 0.25) -> Scene:
    """One film that walks every feature in order — the full product in a minute
    and a half. Section changes (group) get a touch more breathing room."""
    beats = []
    t = 0.5
    last_group = None
    for f in FEATURES:
        if last_group is not None and f.group != last_group:
            t += 0.4                         # a beat of air between sections
        last_group = f.group
        beats.append(Beat(_card(f), t, t + per, anchor=(0.5, 0.44),
                          width=0.54, label=f"{f.group} · {f.title}"))
        t += per + gap
    return Scene("master", size=size, beats=beats,
                 note="The whole product, in order. Lay VO from catalog.md over "
                      "it; music build across the sections. See demo/AI_VIDEO.md.")


def write_catalog_md(path) -> None:
    """The narration script: every feature, its section, card, and VO line."""
    from pathlib import Path
    lines = ["# DreamLayer — full feature catalog\n",
             "Every glasses feature, in demo order. Each row is a beat in the "
             "master film (`master`) and a standalone clip (`<id>`). The card is "
             "the real HUD renderer output.\n",
             "| # | Section | Feature | VO line | Card |",
             "|--:|---------|---------|---------|------|"]
    for i, f in enumerate(FEATURES, 1):
        lines.append(f"| {i} | {f.group} | **{f.title}** | {f.blurb} | "
                     f"`{_card(f).get('type', '')}` |")
    lines.append("\n_Render:_ `python -m dreamlayer.demo catalog out/catalog` — "
                 "writes every per-feature clip, the master film, and this file.\n")
    Path(path).write_text("\n".join(lines))


def build_catalog(out_root: str = "demo_out/catalog") -> dict:
    """Render every per-feature clip + the master film + the script."""
    from pathlib import Path
    from .scene import render_scene
    root = Path(out_root)
    root.mkdir(parents=True, exist_ok=True)
    manifests = {}
    for fid, scene in feature_scenes().items():
        manifests[fid] = render_scene(scene, root / "features" / fid)
    manifests["master"] = render_scene(master_scene(), root / "master")
    write_catalog_md(root / "catalog.md")
    return manifests
