"""PR5 platform-seam tests — every adapter exercised on its fallback path so the
suite is green with none of the optional platform deps installed.
"""
from __future__ import annotations

import pytest


class _Veil:
    def __init__(self, on): self._on = on
    def allow_capture(self): return self._on


class _Clock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t
    def tick(self, dt): self.t += dt


# --- plugins/hookspecs: entry-point discovery + load_into an existing registry
def test_hookspecs_load_into():
    from dreamlayer.plugins import hookspecs

    assert isinstance(hookspecs.discover_entrypoint_plugins(), list)

    class _Reg:
        def __init__(self): self.loaded = []
        def load(self, p): self.loaded.append(p); return True

    reg = _Reg()
    n = hookspecs.load_into(reg, plugins=[object(), object()])
    assert n == 2 and len(reg.loaded) == 2
    # markers are safe to use whether or not pluggy is installed
    @hookspecs.hookimpl
    def _impl(): return 1
    assert _impl() == 1


# --- confluence/emitter_pyee: fan out only when the mesh actually emitted ------
def test_mesh_event_bus_respects_veil():
    from dreamlayer.confluence.emitter_pyee import MeshEventBus

    class _Mesh:
        def __init__(self, live): self._live = live
        def emit(self, kind, body): return {"k": kind, **body} if self._live else None
        def receive(self, wire): return wire.get("member")

    seen = []
    bus = MeshEventBus(_Mesh(live=True))
    bus.on("emit", lambda pkt: seen.append(pkt))
    assert bus.publish_emit("weather", {"state": "calm"}) is not None
    assert seen and seen[0]["k"] == "weather"

    veiled = []
    vbus = MeshEventBus(_Mesh(live=False))
    vbus.on("emit", lambda pkt: veiled.append(pkt))
    assert vbus.publish_emit("weather", {"state": "calm"}) is None
    assert veiled == []            # nothing published when nothing emitted


# --- rosetta_argos: translate_fn is identity-safe without Argos ---------------
def test_rosetta_argos_translate_fn_identity():
    from dreamlayer.rosetta_argos import make_translate_fn
    tr = make_translate_fn()
    assert callable(tr)
    assert tr("hello there friend", "en") == "hello there friend"


# --- hud/render_skia: delegates to the PIL fallback when Skia absent ----------
def test_render_skia_falls_back():
    from dreamlayer.hud.render_skia import make_skia_renderer, available
    sentinel = object()
    render = make_skia_renderer(lambda card: sentinel)
    out = render({"title": "Timer"})
    if not available:
        assert out is sentinel     # went straight to the PIL fallback


# --- ai_brain/server_fastapi: import-safe; app iff fastapi present ------------
def test_server_fastapi_optional():
    from dreamlayer.ai_brain import server_fastapi
    app = server_fastapi.make_app(lambda route, body: {"ok": True})
    if server_fastapi.available:
        assert app is not None
    else:
        assert app is None
        with pytest.raises(RuntimeError):
            server_fastapi.serve(lambda r, b: {})


# --- ai_brain/gemma_backend: injectable transport, safe on failure ------------
def test_gemma_backend_transport():
    from dreamlayer.ai_brain.gemma_backend import GemmaBackend
    g = GemmaBackend(http_post=lambda url, payload: {"response": "  hi  "})
    assert g.chat("yo") == "hi"

    def _boom(url, payload): raise OSError("no server")
    assert GemmaBackend(http_post=_boom).chat("yo") == ""


# --- ai_brain/exo_cluster: OpenAI-shape parse + reachability probe -------------
def test_exo_cluster_backend():
    from dreamlayer.ai_brain.exo_cluster import ExoClusterBackend
    reply = {"choices": [{"message": {"content": "clustered"}}]}
    e = ExoClusterBackend(http_post=lambda url, payload: reply)
    assert e.chat("hi") == "clustered"
    # plain {"text": ...} variant
    e2 = ExoClusterBackend(http_post=lambda url, payload: {"text": "plain"})
    assert e2.chat("hi") == "plain"
    assert e.available(http_get=lambda u: {"models": []}) is True
    assert e.available(http_get=lambda u: (_ for _ in ()).throw(OSError())) is False


# --- rem/nightly_mlx: no-op summary without MLX; veil yields no examples -------
def test_nightly_mlx_noop_and_veil():
    from dreamlayer.rem.nightly_mlx import MlxNightlyTrainer

    class _Ring:
        def memories(self): return [{"summary": "lease due friday"}]

    t = MlxNightlyTrainer()
    s = t.train_nightly(_Ring(), privacy=_Veil(True))
    if not t.available:
        assert s.trained is False and s.reason == "mlx unavailable"
    # veil down -> nothing collected regardless of MLX
    assert t._collect(_Ring(), privacy=_Veil(False)) == []


# --- bridge/frame_sdk + noa_patterns: records payloads without the SDK --------
def test_frame_display_and_noa_patterns():
    from dreamlayer.bridge.frame_sdk import FrameDisplay
    from dreamlayer.bridge.noa_patterns import card_to_frame_lines

    lines = card_to_frame_lines({"title": "Maya", "answer": "owes you $20 from lunch"})
    assert lines[0] == "Maya" and any("owes" in ln for ln in lines)

    d = FrameDisplay()
    res = d.connect()
    if not d.available:
        assert res["ok"] is False
    d.show_card({"title": "Maya", "answer": "hi"})
    assert d.sent and d.sent[-1]["kind"] == "card"


# --- pairing_ratelimit: lockout after N fails, cleared by success -------------
def test_lockout_limiter():
    from dreamlayer.pairing_ratelimit import LockoutLimiter
    clk = _Clock()
    lim = LockoutLimiter(max_attempts=3, window_s=60, lockout_s=300, now_fn=clk)
    assert lim.allow("ip1")
    assert lim.record_failure("ip1") is False
    assert lim.record_failure("ip1") is False
    assert lim.record_failure("ip1") is True      # trips lockout
    assert not lim.allow("ip1")
    assert lim.retry_after("ip1") == 300
    clk.tick(301)
    assert lim.allow("ip1")                        # cooldown elapsed
    lim.record_failure("ip1")
    lim.record_success("ip1")                      # good attempt clears state
    assert lim.retry_after("ip1") == 0


# --- orchestrator/presence: gaze dwell accumulates; veil silences -------------
def test_presence_ledger():
    from dreamlayer.orchestrator.presence import PresenceLedger
    clk = _Clock()
    p = PresenceLedger(gap_s=2.0, now_fn=clk)
    p.look("Maya"); clk.tick(1.0)
    p.look("Maya"); clk.tick(1.0)
    p.look("Maya")
    assert p.presence("Maya") == pytest.approx(2.0)
    # veil down does not record
    before = p.presence("Maya")
    clk.tick(1.0)
    p.look("Maya", privacy=_Veil(False))
    assert p.presence("Maya") == before
    assert p.present(min_seconds=1.0)[0][0] == "Maya"


# --- pipelines/lsl_transport: buffer fallback push/drain ----------------------
def test_lsl_transport_buffer():
    from dreamlayer.pipelines.lsl_transport import LslTransport
    lsl = LslTransport(channels=2)
    lsl.push([1.0, 2.0]); lsl.push([3.0, 4.0])
    drained = lsl.drain()
    assert drained == [[1.0, 2.0], [3.0, 4.0]]
    assert lsl.drain() == []       # drain clears


# --- memory/localrecall_api: in-process fallback add/search + veil guard -------
def test_localrecall_local_fallback():
    from dreamlayer.memory.localrecall_api import LocalRecallClient
    c = LocalRecallClient()                     # no base_url -> local store
    assert c.remote is False
    assert c.add("Marcus promised the lease by Friday") is True
    assert c.add("blocked", privacy=_Veil(False)) is False   # veil down
    hits = c.search("lease Friday")
    assert hits and "lease" in hits[0]["text"] and hits[0]["score"] > 0
