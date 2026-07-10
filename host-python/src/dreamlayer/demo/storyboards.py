"""demo/storyboards.py — the first viral clips, as executable scenes.

Each is a 12–15s vertical (9:16) moment built from the *real* HUD cards, timed so
`render_scene` exports the overlays + manifest + preview a compositor drops over
first-person footage. The prose beat-sheets (shot list, VO, earcons) live in
demo/STORYBOARDS.md; these are the same beats, executable.

Design rule for every clip: **trigger → card → human outcome**. One clear
job-to-be-done, one jaw-drop, in a breath.

    from dreamlayer.demo import render_scene
    from dreamlayer.demo.storyboards import SCENES
    render_scene(SCENES["veritas"], "out/veritas")
"""
from __future__ import annotations

from ..hud import cards
from .scene import Scene, Beat


# 1) VERITAS — the number that didn't add up ---------------------------------
# He restates the figure. It's not what he told you last week. You see it before
# you have to decide whether to trust it.
def _veritas() -> Scene:
    return Scene("veritas", size=(1080, 1920), beats=[
        Beat(cards.spoken_caption("Marcus", "We settled at two million, remember?"),
             t_in=1.0, t_out=4.2, anchor=(0.5, 0.82), width=0.6, glow=False,
             label="caption — his earlier line"),
        Beat(cards.spoken_caption("Marcus", "The deal closed at three million."),
             t_in=4.6, t_out=7.6, anchor=(0.5, 0.82), width=0.6, glow=False,
             label="caption — the new figure"),
        Beat(cards.fact_check(
                verdict="self_contradiction", speaker="Marcus",
                claim="The deal closed at three million.",
                basis="earlier: “we settled at two million”",
                corroboration="elevated · seen before"),
             t_in=7.9, t_out=13.5, anchor=(0.5, 0.42), width=0.52,
             label="Veritas fires — content + delivery + pattern"),
    ], note="Two people at a table, POV. Earcon on the Veritas beat: watchout1. "
            "VO (optional): “It remembered what he said last week.”")


# 2) ANSWER-AHEAD — the answer before you speak ------------------------------
# Someone asks you something you should know. It's already at the edge of your
# vision, in time to say it yourself.
def _answer_ahead() -> Scene:
    return Scene("answer_ahead", size=(1080, 1920), beats=[
        Beat(cards.spoken_caption("Priya", "When did we last ship to Denver?"),
             t_in=1.0, t_out=4.5, anchor=(0.5, 0.82), width=0.6, glow=False,
             label="caption — she asks you"),
        Beat(cards.answer_ahead(
                question="When did we last ship to Denver?",
                answer="March 14th — two pallets.",
                speaker="Priya", source="your files"),
             t_in=3.4, t_out=9.5, anchor=(0.5, 0.44), width=0.52,
             label="answer appears while the question still hangs"),
    ], note="POV across a desk. No earcon (silent by design). "
            "VO: “I hadn’t said a word yet.”")


# 3) OWE-SOMEONE — it remembered so you didn't have to -----------------------
# Someone you owe is a minute away. Juno taps you — “Listen!” — with the one
# thing, and what you owe. You hand it over.
def _owe_someone() -> Scene:
    return Scene("owe_someone", size=(1080, 1920), beats=[
        Beat(cards.hark("Marcus is 2 min away — you owe him the lease.",
                        "from your last chat", "normal"),
             t_in=1.2, t_out=5.4, anchor=(0.5, 0.4), width=0.52,
             label="Listen! — the tap on the shoulder"),
        Beat(cards.commitment_recall({
                "person": "Marcus", "task": "Send the signed lease",
                "due": "today", "confidence": 0.82}),
             t_in=5.7, t_out=10.5, anchor=(0.5, 0.44), width=0.52,
             label="what you owe, surfaced"),
        Beat(cards.juno_reply("Handed off. One less thing.", "answer"),
             t_in=10.8, t_out=13.6, anchor=(0.5, 0.45), width=0.5,
             label="human outcome — done"),
    ], note="Walking POV, someone approaches. Earcon on the hark beat: listen1. "
            "VO: “I never opened my phone.”")


# 4) THE TOUR — the whole assistant in one breath ---------------------------
# A montage sizzle: eight of the real cards, one per beat, so a viewer sees the
# *breadth* — brief, faces, answers, truth, memory, voice — not just one trick.
# Needs no footage: the synthetic plate + these overlays render a complete clip.
def _the_tour() -> Scene:
    def b(card, t0, t1, label, y=0.44):
        return Beat(card, t0, t1, anchor=(0.5, y), width=0.54, label=label)
    return Scene("the_tour", size=(1080, 1920), beats=[
        b(cards.morning_brief(
            "Two meetings, and the lease is due Friday.",
            ["Standup at 9:00", "1 new text — Marcus", "File the taxes"]),
          0.6, 4.0, "wake → your day, waiting"),
        b(cards.person_dossier({
            "person": "Priya", "known": True, "last_seen_ago": "3 days ago",
            "last_line": "Send me the Denver numbers.",
            "topics": ["denver", "shipping", "invoice"]}),
          4.3, 8.0, "look → who is this"),
        b(cards.answer_ahead(
            question="When did we last ship to Denver?",
            answer="March 14th — two pallets.", speaker="Priya", source="your files"),
          8.3, 12.2, "the answer before you speak"),
        b(cards.fact_check(
            verdict="self_contradiction", speaker="Marcus",
            claim="The deal closed at three million.",
            basis="earlier: “we settled at two million”",
            corroboration="elevated · seen before"),
          12.5, 16.6, "truth, checked live"),
        b(cards.hark("Marcus is 2 min away — you owe him the lease.",
                     "from your last chat", "normal"),
          16.9, 20.6, "a tap on the shoulder", y=0.4),
        b(cards.object_recall({
            "object": "Keys", "place": "Kitchen table",
            "detail": "beside the blue notebook", "last_seen": "7:42 PM",
            "confidence": 0.9}),
          20.9, 24.6, "where you left it"),
        b(cards.juno_reply("Focus on — the world's turned down.", "action"),
          24.9, 28.2, "Hey Juno, do anything"),
        b(cards.juno_reply("Everything stays with you. Always.", "answer"),
          28.5, 32.0, "local-first · private by design"),
    ], note="No POV footage needed — renders complete over the synthetic plate. "
            "For a cinematic cut, drop AI-generated (Veo/Sora) environment plates "
            "under each beat. VO ties the montage; music on the beat drops. "
            "See demo/AI_VIDEO.md.")


SCENES = {
    "veritas": _veritas(),
    "answer_ahead": _answer_ahead(),
    "owe_someone": _owe_someone(),
    "the_tour": _the_tour(),
}


def build_all(out_root: str = "demo_out") -> dict:
    """Render every storyboard under `out_root/<name>/`. Returns {name: manifest}."""
    from pathlib import Path
    from .scene import render_scene
    out = {}
    for name, scene in SCENES.items():
        out[name] = render_scene(scene, Path(out_root) / name)
    return out
