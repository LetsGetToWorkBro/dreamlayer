"""ops_ingest — extracted Orchestrator method cluster (behaviour-preserving).

A mixin the Orchestrator inherits; every method here still runs on the
coordinator instance (shared self), so all self.<engine> attributes,
the bridge, and the privacy gate resolve exactly as before. No logic
was changed in the move.
"""
from __future__ import annotations

from ..hud import cards
from ..pipelines import speech
from ..pipelines import vision
from ..pipelines.extraction import extract_commitments


def _readable(value) -> str:
    """Natural-language text for a scene field that may be a structured dict.
    ``{"name": "Keys", "near": "..."}`` → ``"Keys"``; a plain string passes
    through; anything else is stringified. Keeps embed/summary text clean."""
    if isinstance(value, dict):
        return str(value.get("name") or value.get("label") or "").strip()
    return str(value or "").strip()


class IngestOps:

    # ------------------------------------------------------------------
    # Vision fn for SceneDescriber (poetic 6-word VLM mode)
    # ------------------------------------------------------------------

    async def _vision_describe(self, jpeg_bytes: bytes, prompt: str) -> str:
        """Async vision callable wired into SceneDescriber.

        Calls the existing vision pipeline in poetic mode: returns a
        short evocative description rather than a structured memory.
        """
        try:
            result = await vision.describe_poetic(jpeg_bytes, prompt, config=self.config)
            return result
        except Exception as exc:
            self.health.record_failure("vision", exc)
            return ""


    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------

    def _build_ann(self, db_path):
        """Persistent HNSW index beside a persistent DB (None for :memory: or
        when usearch isn't installed — the Retriever's exact linear scan is
        the fallback either way). An embedder change rebuilds the index:
        vectors from different embedding spaces never share one."""
        from ..memory.ann_index import PersistentAnnIndex
        from ..memory.embeddings import embedder_signature
        if db_path == ":memory:" or not PersistentAnnIndex.available:
            return None
        sig = embedder_signature(self.embedder)
        stored_sig = self.db.get_setting("embedder_signature")
        stored_dim = self.db.get_setting("embedder_dim")
        if stored_sig == sig and stored_dim:
            dim = int(stored_dim)
        else:
            dim = len(self.embedder.embed("dreamlayer"))
        ann = PersistentAnnIndex(str(db_path) + ".usearch", dim)
        if not ann.live:
            return None
        if stored_sig != sig or (stored_dim and int(stored_dim) != dim):
            ann.rebuild(self.db)
            self.db.set_setting("embedder_signature", sig)
            self.db.set_setting("embedder_dim", str(dim))
        else:
            # Boot drift check (P2-15): adds are batch-persisted, so a hard
            # kill can leave the on-disk index missing the last few vectors
            # the DB has. When the counts disagree, rebuild — O(rows) once at
            # boot — so recall never silently misses recent memories.
            from ..memory.embeddings import unpack_embedding
            embedded = 0
            for m in self.db.memories():
                vec = unpack_embedding(m.get("embedding"))
                if vec and len(vec) == dim:
                    embedded += 1
            if len(ann) != embedded:
                ann.rebuild(self.db)
        return ann


    def ingest_scene(self, scene):
        if not self.privacy.allow_capture():
            return None
        mem = vision.extract_object_memory(scene)
        # object/place can arrive as structured dicts ({"name","near",...}); the
        # embedding and summary must read as natural language, not stringified
        # JSON — otherwise the object's name is drowned out by field keys and
        # punctuation and even a real embedder retrieves it poorly.
        obj = _readable(mem["object"])
        place = _readable(mem["place"])
        detail = _readable(mem["detail"])
        near = mem["object"].get("near", "") if isinstance(mem["object"], dict) else ""
        emb = self.embedder.embed(" ".join(t for t in (obj, near, place, detail) if t))
        mid = self.db.add_memory(
            "object",
            f"{obj} at {place}" if place else obj,
            embedding=emb,
            confidence=mem["confidence"],
            meta=mem,
        )
        self.retriever.index_memory(mid, emb)
        self.bridge.send_card(cards.saved_memory(mem["object"]), event="memory_saved")
        return mid


    def ingest_conversation(self, conv, place_id=None, context=None):
        """Ingest a conversation via the three-tier NLP pipeline."""
        if not self.privacy.allow_capture():
            return []
        db_ids = []
        if isinstance(conv, str):
            transcript = conv
        else:
            parsed = speech.extract_conversation(conv)
            transcript = parsed.get("summary", "")
            emb = self.embedder.embed(transcript)
            conv_mid = self.db.add_memory(
                "conversation",
                transcript,
                embedding=emb,
                confidence=0.7,
                place_id=place_id,
                meta={"person": parsed["participants"][-1] if parsed.get("participants") else None},
            )
            db_ids.append(conv_mid)
            self.retriever.index_memory(conv_mid, emb)
            for c in extract_commitments(conv):
                cid = self.db.add_commitment(c["person"], c["task"], c["due"], conv_mid, c["confidence"])
                db_ids.append(cid)
        events = self.pipeline.ingest(transcript, context=context)
        from ..memory.embeddings import pack_embedding
        for ev in events:
            emb = self.embedder.embed(ev.summary)
            self.db.conn.execute("UPDATE memories SET embedding=? WHERE id=?", (pack_embedding(emb), ev.db_id))
            self.retriever.index_memory(ev.db_id, emb)
            db_ids.append(ev.db_id)
        self.db.conn.commit()
        self.bridge.send_card(cards.saved_memory(""), event="memory_saved")
        return db_ids


    # ------------------------------------------------------------------
    # Passive entrypoints
    # ------------------------------------------------------------------

    def on_scene_frame(self, scene: dict, *, now_ms: int | None = None):
        """Process a scene frame — feeds Dream Mode if active. Ambient camera
        frames ride the frame budget (one per capture interval): on real
        hardware every frame is a capture + a multi-second BLE transfer, so
        the duty cycle is enforced here, not assumed by each lens."""
        # redact-on-ingest + capture provenance (opt-in seam, N2): before a
        # frame reaches Dream Mode or the Vault, blur bystander PII and stamp a
        # C2PA credential. Off by default (attribute None); when wired, the raw
        # frame is replaced in-place so nothing downstream ever sees it.
        cp = getattr(self, "capture_provenance", None)
        if cp is not None:
            raw = scene.get("camera_jpeg") or scene.get("camera_frame")
            if raw:
                res = cp.ingest(raw, privacy=self.privacy)
                if res is None:                 # veiled / strict-refused
                    scene = {k: v for k, v in scene.items()
                             if k not in ("camera_jpeg", "camera_frame")}
                else:
                    scene = dict(scene)
                    key = "camera_jpeg" if scene.get("camera_jpeg") else "camera_frame"
                    scene[key] = res.jpeg
        if self.state.is_dream():
            jpeg = scene.get("camera_jpeg") or scene.get("camera_frame")
            if jpeg and self.frame_budget.allow_ambient(
                    (now_ms / 1000.0) if now_ms is not None else None):
                self.dream.feed_camera(jpeg)
            imu_pose  = scene.get("imu_pose")
            imu_delta = scene.get("imu_delta")
            if imu_pose:
                self.dream.feed_imu(imu_pose, imu_delta or {})
        return self.silent_capture.capture_scene(scene, now_ms=now_ms)


    def on_audio_frame(self, transcript: str, *, context: dict | None = None, now_ms: int | None = None):
        """Process an audio frame — feeds mic data to Dream Mode if active."""
        if self.state.is_dream() and context:
            fft       = context.get("mic_fft")
            amplitude = context.get("mic_amplitude", 0.0)
            if fft is not None:
                self.dream.feed_mic(fft, float(amplitude))
        return self.silent_capture.capture_transcript(transcript, context=context, now_ms=now_ms)


    # ------------------------------------------------------------------
    # Nod to Remember — on-glass IMU gestures (imu_gesture BLE envelope).
    # The classifier (halo-lua/app/imu_gesture.lua) fires a gesture name;
    # the host turns your neck into the save button. No image is stored —
    # a pinned sighting is a single text row.
    # ------------------------------------------------------------------

    def on_imu_gesture(self, gesture: str, confidence: float = 0.0) -> dict:
        """Route an on-glass gesture. NOD_SAVE pins the newest ring memory;
        SHAKE_DISMISS routes to the card-dismissal trust signal (maturity +
        adaptive floors); GLANCE_PEEK / DOUBLE_NOD / TILT_REVEAL surface as
        intents for the peek/confirm/reveal paths. Unknown → ignored, never
        crashes."""
        g = (gesture or "").strip().upper()
        if g == "NOD_SAVE":
            return self.pin_latest(confidence)
        if g == "SHAKE_DISMISS":
            # the wearer swatted the current card away — the same trust signal a
            # tap-dismiss feeds (see _on_event TEL / CARD_DISMISSED)
            self.maturity.observe_card(dismissed=True)
            return {"gesture": g, "dismissed": True}
        if g in ("GLANCE_PEEK", "DOUBLE_NOD", "TILT_REVEAL"):
            return {"gesture": g}
        return {"gesture": g, "ignored": True}

    def pin_latest(self, confidence: float = 0.0) -> dict:
        """Pin the newest ring sighting so it never expires (meta.pinned, honored
        by memory/retention.py) and confirm it on-glass. The entire evidence
        trail stays one text row — nothing is filmed."""
        latest = self.ring.latest(limit=1)
        if not latest:
            return {"pinned": False, "reason": "nothing to pin"}
        ev = latest[0].event
        ev.meta = dict(getattr(ev, "meta", None) or {})
        ev.meta["pinned"] = True
        try:
            mid = self.db.add_memory(
                kind=getattr(ev, "kind", "memory"),
                summary=getattr(ev, "summary", ""),
                confidence=max(float(getattr(ev, "confidence", 0.5)),
                               float(confidence or 0.0)),
                meta=ev.meta)
        except Exception as exc:
            self.health.record_failure("pin", exc)
            return {"pinned": False, "reason": "persist failed"}
        # confirm: the phone plays haptics.confirm off the card earcon; the ring
        # draws its check glyph (the boot-flag Lua wiring, D2b, renders it)
        self.bridge.send_card(cards.saved_memory(getattr(ev, "summary", "")),
                              event="memory_pinned")
        return {"pinned": True, "memory_id": mid, "summary": ev.summary}


    def _premonition_sweep(self) -> None:
        """New ring events teach (and confirm) the recurrence model —
        a landed event hardens any ghost that predicted it."""
        newest = self._premonition_seen_ts
        for buffered in self.ring.since(self._premonition_seen_ts + 1e-6):
            ev = buffered.event
            meta = getattr(ev, "meta", None) or {}
            if meta.get("private"):
                continue
            self.premonition.confirm(getattr(ev, "kind", "memory"),
                                     getattr(ev, "summary", ""),
                                     buffered.ts, meta.get("place"))
            newest = max(newest, buffered.ts)
        self._premonition_seen_ts = newest


    def _tincan_sweep(self) -> None:
        """A finished tap pattern becomes a ping for the bonded peer.
        The app layer drains confluence_outbox to the peer's phone."""
        if self.tincan is None:
            return
        pattern = self.tap_collector.tick()
        if pattern:
            wire = self.tincan.compose(pattern)
            if wire:
                self.confluence_outbox.append(wire)
