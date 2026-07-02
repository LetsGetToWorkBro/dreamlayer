"""cards.py — Python card payload constructors."""
from __future__ import annotations
from . import themes as T


def _d(data, key, alt_keys=(), default=""):
    if isinstance(data, dict):
        for k in (key, *alt_keys):
            if k in data and data[k] is not None:
                return data[k]
    return default


def ready() -> dict:
    return {"type": "ReadyCard", "dismiss_ms": 0}


def saved_memory(label: str) -> dict:
    return {
        "type": "SavedMemoryCard",
        "dismiss_ms": 1200,
        "primary": label,
        "lines": [label],
    }


def query_listening() -> dict:
    return {"type": "QueryListeningCard", "dismiss_ms": 0}


def loading() -> dict:
    return {"type": "LoadingCard", "dismiss_ms": 0}


def object_recall(
    data,
    place: str = "",
    detail: str = "",
    last_seen: str = "",
    confidence: float | None = None,
) -> dict:
    if isinstance(data, dict):
        object_name = _d(data, "object", ("name", "summary"))
        place       = _d(data, "place", ("location",), place)
        detail      = _d(data, "detail", ("near",), detail)
        last_seen   = _d(data, "last_seen", ("footer",), last_seen)
        confidence  = data.get("confidence", confidence)
    else:
        object_name = data

    if len(detail) > 18:
        detail = detail[:17] + "\u2026"

    return {
        "type":       "ObjectRecallCard",
        "dismiss_ms": 3500,
        "object":     object_name,
        "primary":    object_name,
        "place":      place,
        "detail":     detail,
        "last_seen":  last_seen,
        "footer":     last_seen,
        "confidence": confidence,
        "conf_color": T.conf_color(confidence),
        "lines":      [object_name, place, detail, last_seen],
        "layout": {
            "eyebrow":   {"x": 128, "y": 72,  "size": "sm",   "color": T.ACCENT_MEMORY, "tracking": 2},
            "separator": {"x1": 48, "x2": 208, "y": 86},
            "vbar":      {"x": 20, "y1": 98, "y2": 130, "w": 2, "color": T.MEMORY_RAIL},
            "primary":   {"x": 128, "y": 114, "size": "hero", "color": T.TEXT_PRIMARY},
            "detail":    {"x": 128, "y": 146, "size": "md",   "color": T.TEXT_SECONDARY},
            "footer":    {"x": 128, "y": 170, "size": "sm",   "color": T.TEXT_GHOST},
            "conf_dot":  {"x": 128, "y": 192, "r": 3},
        },
    }


def commitment_recall(
    data,
    task: str = "",
    due: str = "",
    confidence: float | None = None,
) -> dict:
    if isinstance(data, dict):
        person     = _d(data, "person")
        task       = _d(data, "task", ("primary",), task)
        due        = _d(data, "due", ("footer",), due)
        confidence = data.get("confidence", confidence)
    else:
        person = data

    return {
        "type":       "CommitmentRecallCard",
        "dismiss_ms": 4000,
        "person":     person,
        "primary":    task,
        "eyebrow":    f"You promised {person}",
        "due":        due,
        "footer":     due,
        "confidence": confidence,
        "conf_color": T.conf_color(confidence),
        "lines":      [f"You promised {person}", task, due],
    }


def proactive_memory(
    data,
    person: str | None = None,
    confidence: float | None = None,
) -> dict:
    if isinstance(data, dict):
        summary    = _d(data, "summary", ("primary",))
        person     = data.get("person", person)
        confidence = data.get("confidence", confidence)
    else:
        summary = data

    footer = f"With {person}" if person else None
    payload: dict = {
        "type":       "ProactiveMemoryCard",
        "dismiss_ms": 3500,
        "primary":    summary,
        "person":     person,
        "confidence": confidence,
        "lines":      ["Last time here", summary, *([f"With {person}"] if person else [])],
    }
    if footer is not None:
        payload["footer"] = footer
    return payload


def person_context(person: str, headline: str = "", detail: str = "") -> dict:
    return {
        "type":     "PersonContextCard",
        "dismiss_ms": 3500,
        "primary":  person,
        "headline": headline,
        "detail":   detail,
        "lines":    [person, headline, detail],
    }


def privacy_veil() -> dict:
    return {
        "type":     "PrivacyVeilCard",
        "dismiss_ms": 0,
        "primary":  "Privacy Veil",
        "lines":    ["Privacy Veil", "Nothing is being captured"],
    }


def error_card(msg: str = "Try again") -> dict:
    return {
        "type":       "ErrorCard",
        "dismiss_ms": 4000,
        "primary":    msg,
        "lines":      ["Connection issue", msg],
    }


error = error_card


def low_confidence() -> dict:
    return {
        "type":       "LowConfidenceCard",
        "dismiss_ms": 3000,
        "primary":    "Not sure",
        "confidence": 0.0,
        "lines":      ["Not sure", "Try rephrasing"],
    }


# ------------------------------------------------------------------ privacy cards

def forget_last_card(label: str = "") -> dict:
    display_label = label if label else "last memory"
    return {
        "type":        "ForgetLastCard",
        "dismiss_ms":  0,
        "label":       display_label,
        "primary":     f"Forget \u201c{display_label}\u201d?",
        "eyebrow":     "MEMORY WIPE",
        "detail":      "Hold to confirm  \u2022  Tap to cancel",
        "footer":      "This cannot be undone",
        "lines":       ["MEMORY WIPE", f"Forget \u201c{display_label}\u201d?", "Hold to confirm"],
        "layout": {
            "eyebrow":   {"x": 128, "y": 68,  "size": "sm",   "color": T.PRIVACY_DANGER,  "tracking": 4},
            "separator": {"x1": 48, "x2": 208, "y": 84},
            "primary":   {"x": 128, "y": 116, "size": "md",   "color": T.TEXT_PRIMARY},
            "detail":    {"x": 128, "y": 148, "size": "sm",   "color": T.TEXT_SECONDARY},
            "footer":    {"x": 128, "y": 172, "size": "sm",   "color": T.PRIVACY_CAUTION},
            "shield":    {"x": 128, "y": 44,  "r": 10,        "color": T.PRIVACY_DANGER},
        },
    }


def private_zone_card(zone: str = "this area") -> dict:
    return {
        "type":        "PrivateZoneCard",
        "dismiss_ms":  0,
        "zone":        zone,
        "primary":     "Private zone",
        "eyebrow":     "CAPTURE SUSPENDED",
        "detail":      zone,
        "footer":      "Memory resumes when you leave",
        "lines":       ["CAPTURE SUSPENDED", "Private zone", zone],
        "layout": {
            "eyebrow":   {"x": 128, "y": 64,  "size": "sm",   "color": T.PRIVACY_CAUTION, "tracking": 3},
            "separator": {"x1": 48, "x2": 208, "y": 80},
            "primary":   {"x": 128, "y": 112, "size": "hero", "color": T.TEXT_PRIMARY},
            "detail":    {"x": 128, "y": 144, "size": "md",   "color": T.TEXT_SECONDARY},
            "footer":    {"x": 128, "y": 168, "size": "sm",   "color": T.TEXT_GHOST},
            "shield":    {"x": 128, "y": 40,  "r": 10,        "color": T.PRIVACY_CAUTION},
        },
    }


def consent_required_card(context: str = "") -> dict:
    ctx_line = context if context else "a new data source"
    return {
        "type":        "ConsentRequiredCard",
        "dismiss_ms":  0,
        "context":     ctx_line,
        "primary":     "Allow access?",
        "eyebrow":     "CONSENT REQUIRED",
        "detail":      ctx_line,
        "footer":      "Hold to allow  \u2022  Tap to deny",
        "lines":       ["CONSENT REQUIRED", "Allow access?", ctx_line],
        "layout": {
            "eyebrow":   {"x": 128, "y": 64,  "size": "sm",   "color": T.WARNING_AMBER,   "tracking": 3},
            "separator": {"x1": 48, "x2": 208, "y": 80},
            "primary":   {"x": 128, "y": 112, "size": "hero", "color": T.TEXT_PRIMARY},
            "detail":    {"x": 128, "y": 144, "size": "md",   "color": T.TEXT_SECONDARY},
            "footer":    {"x": 128, "y": 168, "size": "sm",   "color": T.WARNING_AMBER},
            "lock":      {"x": 128, "y": 40,  "r": 10,        "color": T.WARNING_AMBER},
        },
    }


def live_caption_card(
    original: str = "",
    translation: str = "",
    src_lang: str = "es",
    dst_lang: str = "en",
    confidence: float | None = None,
    speaker: str | None = None,
) -> dict:
    eyebrow_parts = [src_lang.upper(), "\u2192", dst_lang.upper()]
    if speaker:
        eyebrow_parts = [speaker.split()[0]] + eyebrow_parts
    eyebrow = " ".join(eyebrow_parts)

    primary = translation if translation else original
    if len(primary) > 48:
        primary = primary[:47] + "\u2026"
    footer = original if translation else ""
    if len(footer) > 48:
        footer = footer[:47] + "\u2026"

    return {
        "type":        "LiveCaptionCard",
        "dismiss_ms":  0,
        "original":    original,
        "translation": translation,
        "src_lang":    src_lang,
        "dst_lang":    dst_lang,
        "speaker":     speaker,
        "primary":     primary,
        "eyebrow":     eyebrow,
        "footer":      footer,
        "confidence":  confidence,
        "conf_color":  T.conf_color(confidence),
        "lines":       [eyebrow, primary, footer],
        "layout": {
            "eyebrow":   {"x": 128, "y": 62,  "size": "sm",   "color": T.ACCENT_MEMORY,   "tracking": 2},
            "separator": {"x1": 48, "x2": 208, "y": 78},
            "primary":   {"x": 128, "y": 114, "size": "md",   "color": T.TEXT_PRIMARY},
            "footer":    {"x": 128, "y": 160, "size": "sm",   "color": T.TEXT_GHOST},
            "conf_dot":  {"x": 128, "y": 185, "r": 3},
            "lang_pill": {"x": 128, "y": 40,  "color": T.ACCENT_MEMORY_DIM},
        },
    }


# ------------------------------------------------------------------ lens cards

def truth_gauge_card(
    verdict: str = "UNCERTAIN",
    stages: list[dict] | None = None,
    confidence: float | None = None,
    deception_prob: float = 0.0,
    origin: dict | None = None,
    footer: str = "",
) -> dict:
    """TruthLensCard — 9-ring gauge (Halo Cinema v1, Phase 4).

    One ring per analysis stage (face, au, voice, prosody, linguistic,
    narrative, fusion, aggregate, verdict). Each stage dict carries
    {name, confidence, direction} where direction colors the ring:
    truthful → accent_success, deceptive → accent_attention,
    insufficient → text_ghost. Entry uses the Truth Ripple signature from
    `origin` (eye landmark); reduce_motion draws all rings statically.
    """
    return {
        "type":           "TruthLensCard",
        "dismiss_ms":     5000,
        "verdict":        verdict,
        "primary":        verdict,
        "confidence":     confidence,
        "deception_prob": round(deception_prob, 3),
        "stages":         stages or [],
        "origin":         origin or {"x": 128, "y": 96},
        "footer":         footer,
        "lines":          ["TRUTH LENS", verdict],
    }


# ------------------------------------------------------------------ dream cards

def world_anchor_card(
    summary: str = "",
    place: str = "",
    ts_label: str = "",
    confidence: float | None = None,
) -> dict:
    """WorldAnchorCard — ghost echo of a memory at the current location.

    Shown automatically in Dream Mode when the user is at a place with
    memory anchors.  Low opacity, long dismiss, never intrusive.
    dismiss_ms=8000 so it fades after 8 seconds.
    """
    detail = f"{place}  \u2022  {ts_label}" if place and ts_label else (place or ts_label)
    return {
        "type":        "WorldAnchorCard",
        "dismiss_ms":  8000,
        "summary":     summary,
        "place":       place,
        "ts_label":    ts_label,
        "primary":     summary,
        "eyebrow":     "MEMORY ECHO",
        "detail":      detail,
        "footer":      ts_label,
        "confidence":  confidence,
        "conf_color":  T.conf_color(confidence),
        "opacity":     0.20,   # hint to renderer: render at 20% opacity
        "lines":       ["MEMORY ECHO", summary, detail],
        "layout": {
            "eyebrow":   {"x": 128, "y": 200, "size": "sm",   "color": T.TEXT_GHOST,    "tracking": 3},
            "primary":   {"x": 128, "y": 220, "size": "sm",   "color": T.TEXT_GHOST},
            "detail":    {"x": 128, "y": 236, "size": "sm",   "color": T.TEXT_GHOST},
        },
    }


def synesthesia_card(
    description: str = "",
    confidence: float | None = None,
) -> dict:
    """SynesthesiaCard — VLM 6-word poetic scene description.

    Rendered as hero text in the current dream palette color.
    Updates every ~4 seconds as the scene changes.
    dismiss_ms=4000 so it fades and is replaced by the next description.
    """
    # Trim to a sensible display length
    display = description[:72] if len(description) > 72 else description
    return {
        "type":        "SynesthesiaCard",
        "dismiss_ms":  4000,
        "description": description,
        "primary":     display,
        "eyebrow":     "DREAM",
        "confidence":  confidence,
        "lines":       ["DREAM", display],
        "layout": {
            "eyebrow":   {"x": 128, "y": 88,  "size": "sm",   "color": T.ACCENT_MEMORY, "tracking": 4},
            "separator": {"x1": 64, "x2": 192, "y": 104},
            "primary":   {"x": 128, "y": 140, "size": "md",   "color": T.TEXT_PRIMARY},
        },
    }


def synesthesia_card_v2(
    description: str = "",
    dominant_color: int = 0x2CC79A,
    shapes: list[dict] | None = None,
    confidence: float | None = None,
) -> dict:
    """SynesthesiaCard v2 (Halo Cinema v1) — phrase + gestural sprite.

    Composes the 6-word phrase (top half, ghost tier) with a 3-shape
    gestural sprite (bottom half, streamed separately as a 128×128 4bpp
    TxSprite anchored at y=128). `shapes` carries the sprite spec so the
    phone preview can draw the identical composition without the sprite
    payload.
    """
    display = description[:72] if len(description) > 72 else description
    return {
        "type":           "SynesthesiaCard",
        "version":        2,
        "dismiss_ms":     4000,
        "description":    description,
        "primary":        display,
        "eyebrow":        "DREAM",
        "dominant_color": dominant_color,
        "shapes":         shapes or [],
        "sprite_seen":    False,
        "confidence":     confidence,
        "lines":          ["DREAM", display],
        "layout": {
            "eyebrow":   {"x": 128, "y": 64,  "size": "sm", "color": T.TEXT_GHOST, "tracking": 4},
            "primary":   {"x": 128, "y": 96,  "size": "md", "color": T.TEXT_PRIMARY},
            "separator": {"x1": 48, "x2": 208, "y": 126},
            "sprite":    {"x": 64,  "y": 128, "w": 128, "h": 128},
        },
    }


def palette_shift_card(
    colors: list[dict] | None = None,
    duration_ms: int = 2000,
    mood: str = "neutral",
) -> dict:
    """PaletteShiftCard — ambient palette animation command.

    Not a traditional display card — it carries palette shift data
    consumed by the Lua palette_shader and never renders UI elements.
    dismiss_ms=0 because it's consumed immediately by the renderer.
    """
    return {
        "type":        "PaletteShiftCard",
        "dismiss_ms":  0,
        "mood":        mood,
        "colors":      colors or [],
        "duration_ms": duration_ms,
        "lines":       [],
    }


# ------------------------------------------------------------------ existing new cards (unchanged)

def commitment_drift(
    data,
    task: str = "",
    person: str = "",
    drift_state: str = "healthy",
    decay: float = 0.0,
    due: str = "",
    confidence: float | None = None,
) -> dict:
    if isinstance(data, dict):
        task        = _d(data, "task", ("summary", "primary"), task)
        person      = _d(data, "person", default=person)
        drift_state = data.get("drift_state", drift_state)
        decay       = data.get("decay", decay)
        due         = _d(data, "due", ("footer",), due)
        confidence  = data.get("confidence", confidence)

    _STATE_COLORS = {
        "blooming":  T.ACCENT_SUCCESS,
        "healthy":   T.ACCENT_MEMORY,
        "drifting":  T.CONFIDENCE_MED,
        "cracking":  T.WARNING_AMBER,
        "shattered": T.ACCENT_ERROR,
    }
    state_color = _STATE_COLORS.get(drift_state, T.TEXT_SECONDARY)

    return {
        "type":        "CommitmentDriftCard",
        "dismiss_ms":  4500,
        "task":        task,
        "person":      person,
        "drift_state": drift_state,
        "decay":       round(decay, 3),
        "due":         due,
        "primary":     task,
        "eyebrow":     drift_state.upper(),
        "footer":      due,
        "confidence":  confidence,
        "conf_color":  T.conf_color(confidence),
        "state_color": state_color,
        "lines":       [drift_state.upper(), task, due],
        "layout": {
            "eyebrow":    {"x": 128, "y": 64,  "size": "sm",   "color": state_color, "tracking": 3},
            "separator":  {"x1": 48, "x2": 208, "y": 80},
            "primary":    {"x": 128, "y": 112, "size": "hero", "color": T.TEXT_PRIMARY},
            "decay_bar":  {"x": 128, "y": 148, "fill": round(decay, 3), "color": state_color},
            "footer":     {"x": 128, "y": 168, "size": "sm",   "color": T.TEXT_GHOST},
        },
    }


def time_scrub_node(
    summary: str = "",
    kind: str = "object",
    ts_label: str = "",
    index: int = 0,
    total: int = 1,
    confidence: float | None = None,
) -> dict:
    return {
        "type":       "TimeScrubNodeCard",
        "dismiss_ms": 0,
        "index":      index,
        "total":      total,
        "kind":       kind,
        "summary":    summary,
        "primary":    summary,
        "ts_label":   ts_label,
        "footer":     ts_label,
        "confidence": confidence,
        "lines":      [summary, ts_label],
        "layout": {
            "progress": {"value": index / max(total - 1, 1)},
            "eyebrow":  {"x": 128, "y": 56,  "size": "sm",   "color": T.ACCENT_MEMORY, "tracking": 2},
            "primary":  {"x": 128, "y": 100, "size": "hero", "color": T.TEXT_PRIMARY},
            "footer":   {"x": 128, "y": 148, "size": "sm",   "color": T.TEXT_GHOST},
        },
    }


def deviation_alert(
    prior_summary: str = "",
    new_summary: str = "",
    score: float = 0.0,
    prior_confidence: float = 0.0,
    new_confidence: float = 0.0,
) -> dict:
    return {
        "type":             "DeviationAlertCard",
        "dismiss_ms":       5000,
        "score":            round(score, 3),
        "prior_summary":    prior_summary,
        "prior_confidence": prior_confidence,
        "new_summary":      new_summary,
        "new_confidence":   new_confidence,
        "primary":          new_summary,
        "eyebrow":          "Sounds different\u2026",
        "footer":           prior_summary,
        "lines":            ["Sounds different\u2026", new_summary, prior_summary],
        "layout": {
            "eyebrow":   {"x": 128, "y": 64,  "size": "sm",   "color": T.WARNING_AMBER, "tracking": 2},
            "separator": {"x1": 48, "x2": 208, "y": 80},
            "primary":   {"x": 128, "y": 108, "size": "md",   "color": T.TEXT_PRIMARY},
            "divider":   {"x1": 80, "x2": 176, "y": 132},
            "footer":    {"x": 128, "y": 156, "size": "sm",   "color": T.TEXT_GHOST},
            "score_dot": {"x": 128, "y": 178, "r": 4,         "color": T.ACCENT_ATTENTION},
        },
    }


ALL_SAMPLES: dict[str, dict] = {
    "ready":               ready(),
    "saved_memory":        saved_memory("House keys"),
    "query_listening":     query_listening(),
    "loading":             loading(),
    "object_recall":       object_recall({
        "object":     "Keys",
        "place":      "Kitchen table",
        "detail":     "Beside blue notebook",
        "last_seen":  "Last seen 7:42 PM",
        "confidence": 0.88,
    }),
    "commitment_recall":   commitment_recall({
        "person":     "Jordan",
        "task":       "Send the invoice",
        "due":        "Tomorrow before noon",
        "confidence": 0.72,
    }),
    "proactive_memory":    proactive_memory({
        "summary":    "You discussed the invoice",
        "person":     "Jordan",
        "confidence": 0.70,
    }),
    "person_context":      person_context(
        "Jordan", headline="Sent invoice Wed", detail="Last seen today"
    ),
    "truth_gauge":         truth_gauge_card(
        verdict="ELEVATED",
        confidence=0.74,
        deception_prob=0.71,
        footer="Jordan",
        stages=[
            {"name": "face",       "confidence": 0.92, "direction": "truthful"},
            {"name": "au",         "confidence": 0.61, "direction": "deceptive"},
            {"name": "voice",      "confidence": 0.55, "direction": "deceptive"},
            {"name": "prosody",    "confidence": 0.48, "direction": "deceptive"},
            {"name": "linguistic", "confidence": 0.35, "direction": "truthful"},
            {"name": "narrative",  "confidence": 0.0,  "direction": "insufficient"},
            {"name": "fusion",     "confidence": 0.74, "direction": "deceptive"},
            {"name": "aggregate",  "confidence": 0.74, "direction": "deceptive"},
            {"name": "verdict",    "confidence": 0.71, "direction": "deceptive"},
        ],
    ),
    "person_context_v2": {
        **person_context(
            "Jordan", headline="Studio Atlas  •  Producer",
            detail="Met 2026-06-24",
        ),
        "why":        "Jordan asked about the invoice deadline",
        "confidence": 0.88,
        "conf_color": T.conf_color(0.88),
        "has_avatar": True,
        "contact_id": "c-jordan-001",
    },
    "privacy_veil":      privacy_veil(),
    "error":               error_card("BLE timeout"),
    "low_confidence":      low_confidence(),
    "commitment_drift":    commitment_drift({
        "task":        "Send invoice",
        "person":      "Jordan",
        "drift_state": "cracking",
        "decay":       0.82,
        "due":         "Tomorrow before noon",
        "confidence":  0.78,
    }),
    "time_scrub_node":     time_scrub_node(
        summary="Keys at kitchen counter",
        kind="object",
        ts_label="09:42",
        index=2,
        total=7,
        confidence=0.91,
    ),
    "deviation_alert":     deviation_alert(
        prior_summary="I'll send the invoice tomorrow",
        new_summary="I never said I'd send anything",
        score=0.71,
        prior_confidence=0.80,
        new_confidence=0.85,
    ),
    "forget_last":         forget_last_card("House keys"),
    "private_zone":        private_zone_card("Home office"),
    "consent_required":    consent_required_card("Calendar access"),
    "live_caption":        live_caption_card(
        original="No te preocupes, yo me encargo",
        translation="Don't worry, I'll take care of it",
        src_lang="es",
        dst_lang="en",
        confidence=0.92,
        speaker="Jordan",
    ),
    # --- dream mode ---
    "world_anchor":        world_anchor_card(
        summary="Keys at kitchen counter",
        place="Kitchen",
        ts_label="09:42",
        confidence=0.88,
    ),
    "synesthesia":         synesthesia_card(
        description="soft amber ritual familiar warmth",
    ),
    "synesthesia_v2":      synesthesia_card_v2(
        description="warm cafe hum, cups and patience",
        dominant_color=0xE06B52,
        shapes=[
            {"kind": "circle",   "x": 44,  "y": 56, "size": 36},
            {"kind": "line",     "x": 64,  "y": 92, "size": 48},
            {"kind": "triangle", "x": 96,  "y": 48, "size": 16},
        ],
    ),
    "palette_shift":       palette_shift_card(
        colors=[{"idx": 1, "y": 420, "cb": 560, "cr": 450}],
        mood="voice",
    ),
}
