"""ai_brain/server/brain_sources.py — the Brain's memory-ingest + recall wiring.

The big-wins batch shipped the parts — LightRAG graph recall, the screenpipe /
ActivityWatch / Immich / Dawarich local sources, the FSRS rehearsal store, the
whole-process egress seal — but nothing on the Brain drove them: no code folded a
desk-activity row into the index, consulted the knowledge graph before the
keyword tier, rehearsed a name you just learned, or wrapped a recall in a signed
"nothing left the device" receipt. This mixin is that glue.

Everything is config-gated and degrades to a clean no-op: absent a source app,
a wheel, or the `sources_sync` switch, the Brain answers exactly as before. All
sources are strictly LOCAL (loopback REST / a read-only local DB / a LAN host
pinned by is_local_endpoint), so ingest never becomes egress.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import List, Optional, Tuple

from ._brain_host import BrainHost

log = logging.getLogger("dreamlayer.brain.sources")

_MAX_DOC_ROWS = 200          # cap rows pulled per source per sync (bounded work)


class SourceOps(BrainHost):

    # ------------------------------------------------------------------
    # Knowledge-graph recall (LightRAG) — "what's connected, and when"
    # ------------------------------------------------------------------

    def _graph_recall(self):
        """The Brain's LightRAG working dir, built once from its OWN local model
        + embedder (so nothing goes to a cloud). None when the wheel is absent or
        no local backend is wired — the caller then falls back to vector recall."""
        if self._graph_built:
            return self._graph
        self._graph_built = True
        self._graph = None
        backend = getattr(self, "_backend", None)
        if backend is None:
            return None
        try:
            from ...memory.graph_recall import default_graph_recall
            self._graph = default_graph_recall(
                str(self.cfg_dir / "graph"),
                llm_fn=getattr(backend, "chat", None),
                embed_fn=getattr(backend, "embed", None))
        except Exception as exc:                       # noqa: BLE001 — never fail wiring
            log.info("[sources] graph recall unavailable: %s", exc)
            self._graph = None
        return self._graph

    def graph_answer(self, query: str) -> Optional[str]:
        """Answer over the memory graph (entity + time edges), or None. Consulted
        by Brain.ask BEFORE the keyword tier so 'what did the doctor say about my
        knee in March' resolves by connection, not just cosine similarity."""
        g = self._graph_recall()
        if g is None:
            return None
        try:
            return g.answer(query)
        except Exception as exc:                       # noqa: BLE001
            log.debug("[sources] graph answer failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Local memory sources → the index (and the graph)
    # ------------------------------------------------------------------

    def collect_source_docs(self) -> List[Tuple[str, str]]:
        """Pull recent rows from every ENABLED local source as (name, text)
        documents for the index. Each source is best-effort and []-on-absence;
        one broken source never sinks the batch. Strictly local by construction:
        screenpipe (read-only local DB), ActivityWatch (loopback REST), Immich /
        Dawarich (a LAN host pinned by is_local_endpoint)."""
        docs: List[Tuple[str, str]] = []
        docs.extend(self._screen_docs())
        docs.extend(self._desk_docs())
        docs.extend(self._immich_docs())
        docs.extend(self._dawarich_docs())
        return docs

    def _screen_docs(self) -> List[Tuple[str, str]]:
        try:
            from ...memory.source_screenpipe import default_screen_source
            src = default_screen_source()
            if src is None:
                return []
            out = []
            for r in src.recent(limit=_MAX_DOC_ROWS,
                                 since_ts=self.last_sources_sync):
                app = f" [{r['app']}]" if r.get("app") else ""
                out.append((f"screen:{r['kind']}", f"{r['text']}{app}"))
            return out
        except Exception as exc:                       # noqa: BLE001
            self.health.record_failure("sources:screenpipe", exc)
            return []

    def _desk_docs(self) -> List[Tuple[str, str]]:
        try:
            from ...memory.source_activitywatch import default_desk_source
            src = default_desk_source()
            if src is None:
                return []
            return [("desk", r["text"]) for r in src.recent(limit=_MAX_DOC_ROWS)]
        except Exception as exc:                       # noqa: BLE001
            self.health.record_failure("sources:activitywatch", exc)
            return []

    def _immich_docs(self) -> List[Tuple[str, str]]:
        base = getattr(self.config, "immich_base_url", "")
        if not base:
            return []
        try:
            from ...memory.source_immich import default_immich
            src = default_immich(base, getattr(self.config, "immich_api_key", ""))
            if src is None:
                return []
            return [("photo-memory", m["title"]) for m in src.memories(limit=50)]
        except Exception as exc:                       # noqa: BLE001
            self.health.record_failure("sources:immich", exc)
            return []

    def _dawarich_docs(self) -> List[Tuple[str, str]]:
        base = getattr(self.config, "dawarich_url", "")
        if not base:
            return []
        try:
            from ...memory.source_dawarich import default_dawarich
            src = default_dawarich(base, getattr(self.config, "dawarich_api_key", ""))
            if src is None:
                return []
            pts = src.points(limit=_MAX_DOC_ROWS)
            if not pts:
                return []
            # a light summary line, not a raw coordinate dump — the graph/index
            # want places-over-time, and coordinates aren't searchable text.
            return [("places", f"{len(pts)} location points logged")]
        except Exception as exc:                       # noqa: BLE001
            self.health.record_failure("sources:dawarich", exc)
            return []

    def sync_sources(self) -> dict:
        """Fold every enabled local source into the index (and the graph, when
        built). Returns {docs, sources}. Never raises; updates the sync
        watermark so the next pass only pulls what's new (where a source
        supports it)."""
        docs = self.collect_source_docs()
        if docs:
            try:
                self.index.add_documents(docs)
            except Exception as exc:                   # noqa: BLE001
                self.health.record_failure("sources:index", exc)
            g = self._graph_recall()
            if g is not None:
                for _name, text in docs:
                    try:
                        g.index(text)
                    except Exception:                  # noqa: BLE001
                        pass
            self.activity.add("sources", f"Folded {len(docs)} memory row(s)")
        self.last_sources_sync = self._now_ts()
        return {"docs": len(docs), "sources": True}

    def maybe_sync_sources(self) -> dict:
        """Sync only when the wearer switched it on (config.sources_sync). Called
        from reindex so a normal folder reindex also freshens the live sources."""
        if not getattr(self.config, "sources_sync", False):
            return {"docs": 0, "sources": False}
        return self.sync_sources()

    def start_source_sync(self, interval: float = 900.0) -> None:
        """Poll the local sources on a daemon thread (matches start_calendar_sync).
        Idempotent; a first tick runs promptly, then every `interval` seconds."""
        if self._src_stop is not None:
            return
        stop = threading.Event()
        self._src_stop = stop

        def loop():
            first = True
            while not stop.wait(3.0 if first else interval):
                first = False
                try:
                    self.maybe_sync_sources()
                except Exception:                      # noqa: BLE001
                    log.warning("[sources] sync tick failed", exc_info=True)

        threading.Thread(target=loop, daemon=True, name="dreamlayer-sources").start()

    def stop_source_sync(self) -> None:
        if self._src_stop is not None:
            self._src_stop.set()
            self._src_stop = None

    def _now_ts(self) -> float:
        return time.time()

    # ------------------------------------------------------------------
    # FSRS rehearsal — the moment right after you meet someone
    # ------------------------------------------------------------------

    def _rehearsal(self):
        """The Brain's rehearsal store, built once. Always works (a JSON store);
        FSRS sharpens the schedule when the wheel is installed."""
        store = getattr(self, "_rehearsal_store", None)
        if store is None:
            from ...memory.rehearsal_fsrs import default_rehearsal
            store = default_rehearsal(self.cfg_dir)
            self._rehearsal_store = store
        return store

    def rehearse_person(self, name: str, note: str = "") -> Optional[dict]:
        """Start rehearsing a name (and how you know them) so it doesn't slip.
        First review is due in ten minutes — right after the introduction."""
        name = (name or "").strip()
        if not name:
            return None
        text = name if not note else f"{name} — {note}"
        try:
            return self._rehearsal().add(f"person:{name.lower()}", "name", text)
        except Exception as exc:                       # noqa: BLE001
            log.debug("[sources] rehearse_person failed: %s", exc)
            return None

    def rehearsals_due(self, limit: int = 5) -> list:
        """What's worth resurfacing right now (names most-overdue first) — the
        feed the morning brief and the Rehearsal surface read."""
        try:
            return self._rehearsal().due(limit)
        except Exception as exc:                       # noqa: BLE001
            log.debug("[sources] rehearsals_due failed: %s", exc)
            return []

    def review_rehearsal(self, item_id: str, rating: str = "good") -> Optional[dict]:
        """Record a rehearsal outcome and schedule the next one."""
        try:
            return self._rehearsal().review(item_id, rating)
        except Exception as exc:                       # noqa: BLE001
            log.debug("[sources] review_rehearsal failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Sealed recall — a signed "nothing left the device" receipt
    # ------------------------------------------------------------------

    def sealed_recall(self, query: str) -> dict:
        """Answer a query under a whole-process egress seal: the recall runs
        no_cloud (on-device tiers only), and a signed 'egress_seal' record is
        folded into the tamper-evident activity ledger attesting nothing left the
        device. Returns {answer, tier, sources, receipt}. The receipt is the
        proof a wearer — or a bystander — can verify independently."""
        from ...privacy.egress_seal import sealed_attest
        ans = None
        with sealed_attest(self.activity):
            ans = self.ask(query, no_cloud=True)
        return {
            "answer": (ans.text if ans is not None else ""),
            "tier": (ans.tier if ans is not None else ""),
            "sources": (list(ans.sources) if ans is not None else []),
            "receipt": self.activity.receipt(),
        }
