"""truth_lens/analyzer.py — TruthLens main orchestrator."""
from __future__ import annotations
import time
from typing import Optional
import numpy as np
from .face_embed import FaceEmbedder, cosine_similarity
from .au_detector import AUDetector
from .prosody import ProsodyAnalyzer
from .linguistic import LinguisticAnalyzer
from .fusion import FusionEngine
from .renderer import TruthLensRenderer
from .narrative_store import NarrativeStore
from .schema import AUFrame, ProsodyFrame, LinguisticFrame, TruthLensResult

EMIT_COOLDOWN_S = 3.0
FACE_MATCH_THRESHOLD = 0.65


class _AlwaysOn:
    def allow_capture(self) -> bool:
        return True


class TruthLens:
    """9-stage multimodal deception analysis orchestrator.

    (Formerly LieLens — renamed to TruthLens per DreamLayer brand architecture.)
    """

    def __init__(self, contact_registry=None, cooldown_s=EMIT_COOLDOWN_S,
                 privacy=None, memory_backend=None):
        self._contacts = contact_registry or {}
        self._cooldown_s = cooldown_s
        self._privacy = privacy or _AlwaysOn()
        self._embedder = FaceEmbedder()
        self._au_detector = AUDetector()
        self._prosody = ProsodyAnalyzer()
        self._linguistic = LinguisticAnalyzer()
        self._fusion = FusionEngine()
        self._renderer = TruthLensRenderer()
        self._store = NarrativeStore(memory_backend)
        self._current_au = None
        self._current_prosody = None
        self._current_linguistic = None
        self._current_contact_id = None
        self._current_contact_name = None
        self._last_emit: float = 0.0

    def feed_frame(self, camera_frame) -> None:
        if not self._privacy.allow_capture():
            return
        au = self._embedder.process_frame(camera_frame)
        if au is None:
            return
        au = self._au_detector.process(au)
        self._current_au = au
        if au.embedding and self._contacts:
            cid, score = self._match_contact(au.embedding)
            if cid and score >= FACE_MATCH_THRESHOLD:
                self._current_contact_id = cid
                self._current_contact_name = (
                    self._contacts[cid].get("name") if cid else None)

    def feed_audio(self, mic_fft, amplitude) -> None:
        if not self._privacy.allow_capture():
            return
        prosody = self._prosody.feed(mic_fft, amplitude)
        if prosody is not None:
            self._current_prosody = prosody

    def feed_transcript(self, text) -> None:
        if not self._privacy.allow_capture():
            return
        ling = self._linguistic.analyse(text)
        if ling is not None:
            self._current_linguistic = ling

    def tick(self) -> Optional[TruthLensResult]:
        if not self._privacy.allow_capture():
            return None
        now = time.monotonic()
        if now - self._last_emit < self._cooldown_s:
            return None
        if self._current_au is None and self._current_prosody is None:
            return None
        baseline = None
        if self._current_contact_id:
            baseline = self._store.get_baseline(self._current_contact_id)
        credibility = self._fusion.fuse(
            self._current_au, self._current_prosody,
            self._current_linguistic, baseline)
        if credibility.confidence < 0.1 and credibility.deception_prob < 0.5:
            return None
        result = TruthLensResult(
            credibility=credibility,
            contact_id=self._current_contact_id,
            contact_name=self._current_contact_name,
            au_frame=self._current_au,
            prosody_frame=self._current_prosody,
            linguistic_frame=self._current_linguistic,
        )
        card = self._renderer.render(result)
        if card is None:
            return None
        if self._current_contact_id:
            self._store.update_baseline(
                self._current_contact_id, self._current_au,
                self._current_prosody, self._current_linguistic)
            if credibility.deception_prob > 0.65:
                self._store.log_anomaly(
                    self._current_contact_id,
                    credibility.deception_prob,
                    credibility.dominant_channel)
        self._last_emit = now
        return result

    def reset(self) -> None:
        self._current_au = None
        self._current_prosody = None
        self._current_linguistic = None
        self._current_contact_id = None
        self._current_contact_name = None
        self._last_emit = 0.0

    def _match_contact(self, embedding):
        best_id, best_score = None, 0.0
        for cid, info in self._contacts.items():
            emb = info.get("embedding")
            if emb:
                score = cosine_similarity(embedding, emb)
                if score > best_score:
                    best_score, best_id = score, cid
        return best_id, best_score
