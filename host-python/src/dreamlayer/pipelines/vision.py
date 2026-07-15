"""pipelines/vision.py — Vision pipeline for DreamLayer.

Provides two modes:
  extract_object_memory(scene)         — structured memory extraction (existing)
  describe_poetic(jpeg, prompt, cfg)   — Dream Mode: 6-word poetic VLM description
"""
from __future__ import annotations

import base64
import os
from typing import Any

from ..memory.privacy import AlwaysOnGate


def extract_object_memory(scene: dict) -> dict:
    """Extract a structured object memory from a scene dict.

    scene keys used: object, place, detail, last_seen, confidence
    Returns a memory dict with the same keys, defaulting gracefully.
    """
    if isinstance(scene, dict):
        return {
            "object":     scene.get("object", "unknown"),
            "place":      scene.get("place", ""),
            "detail":     scene.get("detail", ""),
            "last_seen":  scene.get("last_seen", ""),
            "confidence": float(scene.get("confidence", 0.5)),
        }
    return {"object": str(scene), "place": "", "detail": "", "last_seen": "", "confidence": 0.5}


async def describe_poetic(jpeg_bytes: bytes, prompt: str, config: Any = None,
                          privacy: Any = None, cloud_ok: Any = None) -> str:
    """Call vision-language model for a short poetic scene description.

    Used exclusively by Dream Mode SceneDescriber.  Returns a string of
    ~6 evocative words.  Falls back to empty string on any error.

    Requires OPENAI_API_KEY (or config.openai_api_key) and the openai package.
    Model: gpt-4o with vision (cheapest vision model, ~0.01 USD per call).
    Swap the model string for liquid/lfm2-vl-450m once Liquid API is stable.

    Defense-in-depth capture gate (audit 2026-07-15): sending the raw camera
    JPEG to a cloud VLM is the most sensitive egress this pipeline performs. The
    producer (orchestrator SceneDescriber._vision_describe) already refuses when
    the veil is up or the Cloud switch is off, but a DIRECT caller of this
    primitive would otherwise bypass the veil entirely. So this function ALSO
    consults an optional ``privacy`` gate and refuses — empty string, no cloud
    POST — when ``allow_capture()`` is False. Default ``AlwaysOnGate()`` keeps
    the isolated/library posture permissive and every existing call signature
    working.

    Cloud-switch gate (audit 2026-07-14 CRITICAL #3): egress here was gated only
    on the API KEY being present — so a key with the wearer's Cloud switch OFF
    (or incognito) still shipped the raw frame to the cloud. A mere key is not
    consent. This primitive now ALSO refuses when the Cloud switch reads off,
    via EITHER an explicit ``cloud_ok()`` predicate (the shape the orchestrator
    wires to ``brain.cloud_opt_in``, which incognito forces off) OR a ``config``
    exposing ``cloud_ready()`` (BrainConfig: lan_only / cloud_enabled / key). A
    key without the switch no longer egresses. Both default absent, so the
    library/offline call signature is unchanged.
    """
    gate = privacy or AlwaysOnGate()
    if not gate.allow_capture():
        return ""                     # veiled: raw frame never leaves the device

    # Cloud switch: an explicit predicate wins; else a config that knows its own
    # cloud posture (cloud_ready) is honored. Absent both, unchanged behaviour.
    if cloud_ok is not None and not cloud_ok():
        return ""                     # Cloud switch off → no raw frame egress
    cloud_ready = getattr(config, "cloud_ready", None)
    if callable(cloud_ready) and not cloud_ready():
        return ""                     # config's own Cloud switch off → no egress

    api_key = (
        getattr(config, "openai_api_key", None)
        or os.environ.get("OPENAI_API_KEY", "")
    )
    if not api_key:
        return ""

    try:
        import openai  # type: ignore
        client = openai.AsyncOpenAI(api_key=api_key)

        b64 = base64.b64encode(jpeg_bytes).decode()
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=30,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type":  "image_url",
                            "image_url": {
                                "url":    f"data:image/jpeg;base64,{b64}",
                                "detail": "low",   # cheapest vision tier
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        return (response.choices[0].message.content or "").strip()
    except Exception:
        return ""
