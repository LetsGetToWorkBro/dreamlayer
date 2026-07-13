"""lenses.py — the six-lens mental model of DreamLayer.

Twenty-odd shipped features are a hard story; six lenses are an easy one.
This is the single source of truth for that grouping — pure, descriptive
metadata (no behaviour), so the README, the phone app, and any onboarding
UI can present the same clean model. Every feature keeps its own module and
name; this only says which lens it lives under.

    from dreamlayer.lenses import LENSES, lens_of

Structure: six primary LENSES, plus the SPINE (Privacy Veil — always on)
and ATMOSPHERE (ambient light/feel). Nothing here changes how anything runs.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Feature:
    key: str
    name: str
    blurb: str
    module: str          # where it lives (dotted path or file)


@dataclass(frozen=True)
class Lens:
    key: str
    name: str
    tagline: str
    features: list[Feature] = field(default_factory=list)


LENSES: list[Lens] = [
    Lens("memory", "Memory", "your life, remembered", [
        Feature("dream_mode", "Dream Mode", "ambient sensing; the resting state",
                "dreamlayer.dream_mode"),
        Feature("ghost_layer", "Ghost Layer", "memory echoes anchored to places",
                "dreamlayer.dream_mode"),
        Feature("lucid_recall", "Lucid Recall", "ask and receive — now over your files too",
                "dreamlayer.lucid_recall"),
        Feature("rem", "REM", "the glasses dream the day; dreaming is consolidation",
                "dreamlayer.rem"),
        Feature("yesterlight", "Yesterlight", "roll your head back, replay the room's light",
                "dreamlayer.dream_mode.yesterlight"),
        Feature("premonition", "Premonition", "your rhythms shimmer ahead of now",
                "dreamlayer.dream_mode.premonition"),
        Feature("waypath", "Waypath Lens", "point-me-to-my-things: direction + distance from your anchors",
                "dreamlayer.orchestrator.waypath"),
    ]),
    Lens("people", "People", "who's around you", [
        Feature("social_lens", "Social Lens", "recognise your own contacts (never strangers)",
                "dreamlayer.social_lens"),
        Feature("timbre", "Timbre", "known voices glow at the rim; strangers are static",
                "dreamlayer.dream_mode.timbre_reactor"),
        Feature("name_capture", "Name Capture", "remember a name you were told, on consent",
                "dreamlayer.social_lens.introduction"),
    ]),
    Lens("truth", "Truth", "what's true, and where beliefs come from", [
        Feature("truth_lens", "Truth Lens", "others' credibility (explicit, never passive)",
                "dreamlayer.truth_lens"),
        Feature("candor", "Candor", "your own story, kept consistent",
                "dreamlayer.orchestrator.consistency"),
        Feature("provenance", "Provenance Lens", "trace a belief to its origin and standing",
                "dreamlayer.orchestrator.provenance"),
    ]),
    Lens("world", "World", "understand what you look at", [
        Feature("juno", "Juno", "look at anything → know it (recognise + panel)",
                "dreamlayer.object_lens"),
        Feature("label", "Label Lens", "your own facts about a product: dietary rules, ownership, returns",
                "dreamlayer.object_lens.label"),
        Feature("taste", "TasteLens", "a shelf or menu → the pick, ranked by your rules (vetoes, budget, rating)",
                "dreamlayer.orchestrator.taste"),
        Feature("ai_brain", "AI Brain", "name/explain anything; ask your own files",
                "dreamlayer.ai_brain"),
        Feature("rosetta", "Rosetta Lens", "translate text you look at (the eye)",
                "dreamlayer.rosetta"),
        Feature("puente", "Puente", "live voice translation (the ear)",
                "dreamlayer.orchestrator.puente_bridge"),
        Feature("scholar", "Scholar", "read a test → the answer; a form → what to write in each field; dense text → plain words",
                "dreamlayer.orchestrator.scholar"),
    ]),
    Lens("life", "Life", "do, keep, and build", [
        Feature("commitment_drift", "Commitment Drift", "promises as physics objects",
                "dreamlayer.orchestrator.commitment_drift"),
        Feature("saga", "Saga", "your commitments as a personal RPG",
                "dreamlayer.orchestrator.quest"),
        Feature("reality_compiler", "Reality Compiler", "Rehearsal + Wayfinding → verified Figments",
                "dreamlayer.reality_compiler.v2"),
    ]),
    Lens("together", "Together", "two wearers, one sky", [
        Feature("confluence", "Confluence", "entangled skies, TinCan, weather gifts",
                "dreamlayer.confluence"),
    ]),
]

# always on — the privacy spine
SPINE: list[Feature] = [
    Feature("privacy_veil", "Privacy Veil", "one gesture: fully deaf and blind",
            "dreamlayer.memory.privacy"),
]

# ambient light and feel — atmosphere, not a task
ATMOSPHERE: list[Feature] = [
    Feature("inner_weather", "Inner Weather", "your body churns the core; the room storms the rim",
            "dreamlayer.dream_mode.inner_weather"),
    Feature("prism", "Prism Lens", "the world as a reactive kaleidoscope",
            "halo-lua/display/prism.lua"),
    Feature("palette_cycling", "Palette Cycling", "zero-cost motion by recolouring, not redrawing",
            "halo-lua/display/palette_cycle.lua"),
]


# -- helpers ---------------------------------------------------------------

def all_features() -> list[Feature]:
    feats = [f for lens in LENSES for f in lens.features]
    return feats + SPINE + ATMOSPHERE


def find_feature(key: str) -> Feature | None:
    return next((f for f in all_features() if f.key == key), None)


def lens_of(feature_key: str) -> Lens | None:
    for lens in LENSES:
        if any(f.key == feature_key for f in lens.features):
            return lens
    return None
