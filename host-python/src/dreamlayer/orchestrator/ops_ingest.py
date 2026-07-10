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
        return ann


    def ingest_scene(self, scene):
        if not self.privacy.allow_capture():
            return None
        mem = vision.extract_object_memory(scene)
        emb = self.embedder.embed(f"{mem['object']} {mem['place']} {mem['detail']}")
        mid = self.db.add_memory(
            "object",
            f"{mem['object']} at {mem['place']}",
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
