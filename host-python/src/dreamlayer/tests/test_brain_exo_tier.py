"""The exo cluster as a SELECTABLE model tier, not just an importable file.

`ai_brain/exo_cluster.py` shipped for a long while as the cleanest example of
the failure the reachability audits keep finding: a well-written adapter, in the
Brain's import closure, with a passing unit test, and `ExoClusterBackend`
constructed by nothing. `capability_reachability.py` counted it in the good
column because "the module loads" was the only question being asked.

Wiring it raised a second question that the Ollama tier had already answered the
hard way. `OllamaBackend._endpoint` carries a locality check, a veil gate and an
egress receipt because a remote `ollama_url` had silently shipped the wearer's
notes off-box while reporting tier "laptop" with the counter at 0. exo is a
CLUSTER — reaching another machine is the whole point — so the same gate is the
normal path here, not the edge case, and these tests hold it there.

The other half is honesty about what the tier CANNOT do: exo serves text, so a
look must report blind rather than raise an AttributeError into a swallowed
None, and semantic search must stay off rather than silently degrade to keyword
while the panel claims embeddings are on.
"""
from __future__ import annotations

import pathlib
import tempfile

from dreamlayer.ai_brain.exo_cluster import (DEFAULT_EXO_MODEL, DEFAULT_EXO_URL,
                                             ExoClusterBackend)
from dreamlayer.ai_brain.server.server import Brain
from dreamlayer.ai_brain.server.store import BrainConfig

PANEL = (pathlib.Path(__file__).resolve().parents[1]
         / "ai_brain" / "server" / "panel.py")
SERVER = (pathlib.Path(__file__).resolve().parents[1]
          / "ai_brain" / "server" / "server.py")


def _cfg(**kw) -> BrainConfig:
    c = BrainConfig()
    for k, v in kw.items():
        setattr(c, k, v)
    return c


class TestTheEndpointGate:
    """What `_endpoint` refuses, and why each refusal exists."""

    def test_a_loopback_cluster_answers_and_is_not_egress(self):
        seen = []
        e = ExoClusterBackend(http_post=lambda u, p: {"text": "ok"},
                              config=_cfg(), on_egress=lambda u, r: seen.append((u, r)))
        assert e.chat("hi") == "ok"
        assert seen == [], "loopback is not egress and must leave no receipt"

    def test_a_lan_node_answers_but_leaves_a_receipt(self):
        """The distinction `_is_loopback` exists for. `lan_only` legitimately
        permits this — that is what the mode means — but the prompt still
        crossed the room to another computer, so it is recorded."""
        seen = []
        e = ExoClusterBackend(base_url="http://192.168.1.50:52415",
                              http_post=lambda u, p: {"text": "ok"},
                              config=_cfg(network_mode="lan_only"),
                              on_egress=lambda u, r: seen.append((u, r)))
        assert e.chat("hi") == "ok"
        assert len(seen) == 1 and seen[0][1] is False, seen

    def test_a_remote_cluster_is_counted_as_egress(self):
        seen = []
        e = ExoClusterBackend(base_url="https://exo.example.com",
                              http_post=lambda u, p: {"text": "ok"},
                              config=_cfg(), on_egress=lambda u, r: seen.append((u, r)))
        assert e.chat("hi") == "ok"
        assert len(seen) == 1 and seen[0][1] is True, seen

    def test_a_remote_cluster_is_refused_while_lan_only(self):
        """The gate that matters. Under `lan_only` the shield is up, so the
        request is not made at all — not made and counted, not made."""
        posted = []
        e = ExoClusterBackend(base_url="https://exo.example.com",
                              http_post=lambda u, p: posted.append(u) or {"text": "x"},
                              config=_cfg(network_mode="lan_only"))
        assert e.chat("hi") == ""
        assert posted == [], "the prompt left the device while veiled"

    def test_a_remote_cluster_is_refused_during_quiet_hours(self):
        posted = []
        e = ExoClusterBackend(base_url="https://exo.example.com",
                              http_post=lambda u, p: posted.append(u) or {"text": "x"},
                              config=_cfg(quiet_hours="00:00-23:59"))
        assert e.chat("hi") == ""
        assert posted == []

    def test_a_remote_cluster_with_no_config_fails_closed(self):
        """A bare backend has no posture to consult, so a non-local endpoint is
        REFUSED rather than reached on a guess. The default endpoint is
        loopback, so this costs a bare local backend nothing."""
        posted = []
        e = ExoClusterBackend(base_url="https://exo.example.com",
                              http_post=lambda u, p: posted.append(u) or {"text": "x"})
        assert e.chat("hi") == ""
        assert posted == []

    def test_link_local_metadata_space_is_refused_outright(self):
        """169.254.169.254 is every major cloud's instance-metadata service and
        is never a model endpoint. Refused whatever the posture says."""
        posted = []
        for url in ("http://169.254.169.254", "http://169.254.169.254:52415"):
            e = ExoClusterBackend(base_url=url, config=_cfg(),
                                  http_post=lambda u, p: posted.append(u) or {"text": "x"})
            assert e.chat("hi") == ""
        assert posted == []

    def test_an_empty_url_declines_rather_than_posting_to_a_bare_path(self):
        posted = []
        e = ExoClusterBackend(base_url="", config=_cfg(),
                              http_post=lambda u, p: posted.append(u) or {"text": "x"})
        assert e.chat("hi") == ""
        assert posted == []

    def test_the_probe_is_gated_too(self):
        """`available()` is a request as well. A probe that reaches a remote host
        while the veil is up leaks the same thing in a smaller package."""
        got = []
        e = ExoClusterBackend(base_url="https://exo.example.com",
                              config=_cfg(network_mode="lan_only"))
        assert e.available(http_get=lambda u: got.append(u) or {}) is False
        assert got == []

    def test_the_probe_still_works_locally(self):
        e = ExoClusterBackend(config=_cfg())
        assert e.available(http_get=lambda u: {"models": []}) is True
        assert e.available(
            http_get=lambda u: (_ for _ in ()).throw(OSError())) is False

    def test_the_url_the_poster_receives_is_the_full_endpoint(self):
        seen = []
        e = ExoClusterBackend(config=_cfg(),
                              http_post=lambda u, p: seen.append(u) or {"text": "x"})
        e.chat("hi")
        assert seen == [DEFAULT_EXO_URL + "/v1/chat/completions"], seen


class TestTheParseSurvivedTheRewrite:
    """The two response shapes exo builds actually return."""

    def test_the_openai_shape(self):
        e = ExoClusterBackend(config=_cfg(), http_post=lambda u, p: {
            "choices": [{"message": {"content": " clustered "}}]})
        assert e.chat("hi") == "clustered"

    def test_the_plain_text_shape(self):
        e = ExoClusterBackend(config=_cfg(),
                              http_post=lambda u, p: {"text": "plain"})
        assert e.chat("hi") == "plain"

    def test_a_transport_failure_is_an_empty_answer_not_an_exception(self):
        def boom(u, p):
            raise OSError("no cluster")
        e = ExoClusterBackend(config=_cfg(), http_post=boom)
        assert e.chat("hi") == ""

    def test_a_junk_body_is_an_empty_answer(self):
        e = ExoClusterBackend(config=_cfg(), http_post=lambda u, p: {"nope": 1})
        assert e.chat("hi") == ""


class TestTheTierIsHonestAboutNotSeeing:
    """exo serves `/v1/chat/completions` and no images."""

    def test_the_backend_deliberately_has_no_vision_method(self):
        assert not hasattr(ExoClusterBackend(config=_cfg()), "vision")

    def test_vision_answer_declines_for_a_text_only_backend(self):
        from dreamlayer.ai_brain.server.backends import vision_answer
        assert vision_answer(ExoClusterBackend(config=_cfg()),
                             "a mug", None, "quick") is None

    def test_the_vision_router_reports_blind_rather_than_a_backend_existing(self):
        """`has_vision` used to be `_backend is not None`, which was True here —
        so `explain` called a method that does not exist and the AttributeError
        became a None. A row that advertises sight and then cannot see is worse
        than one that says it is blind."""
        from dreamlayer.ai_brain.server.world_lens import _BrainVisionRouter

        class _B:
            _backend = ExoClusterBackend(config=_cfg())
        assert _BrainVisionRouter(_B()).has_vision() is False

    def test_the_router_still_sees_with_a_vision_capable_backend(self):
        """The other direction, so the fix cannot be "always False"."""
        from dreamlayer.ai_brain.server.world_lens import _BrainVisionRouter

        class _Seeing:
            def vision(self, label, image_b64, want):
                return "a mug"

        class _B:
            _backend = _Seeing()
        assert _BrainVisionRouter(_B()).has_vision() is True

    def test_a_describe_only_backend_still_counts_as_seeing(self):
        """Narrowing the check to `vision` alone broke the OTHER image caller.
        The Synesthesia lens reads frames through `describe(prompt, image_b64)`,
        so a backend offering only that name can see — and four tests said so
        immediately. The question is "can it read an image", not "which name".
        """
        from dreamlayer.ai_brain.server.world_lens import _BrainVisionRouter

        class _Describer:
            def describe(self, prompt, image_b64):
                return "rain beading on cold glass"

        class _B:
            _backend = _Describer()
        assert _BrainVisionRouter(_B()).has_vision() is True

    def test_a_plugin_is_not_granted_vision_on_this_tier(self):
        """`plugin_capabilities` grants "vision" for `model == "ollama"` or a
        ready cloud. A text-only tier must not join that list by accident — a
        plugin told it has vision has no second way to find out it does not."""
        brain = Brain(tempfile.mkdtemp())
        brain.config.model = "exo"
        brain._wire_model()
        assert "vision" not in brain.plugin_capabilities()
        brain.config.model = "ollama"
        brain._wire_model()
        assert "vision" in brain.plugin_capabilities()   # not "always absent"


class TestTheWiring:
    """`_wire_model` — the line that turns the file into a capability."""

    def test_selecting_the_tier_actually_constructs_the_backend(self):
        """The whole point. Before this branch existed, no value of any config
        field could put an `ExoClusterBackend` in `_backend`."""
        brain = Brain(tempfile.mkdtemp())
        brain.config.model = "exo"
        brain.config.exo_url = "http://127.0.0.1:52415"
        brain._wire_model()
        assert isinstance(brain._backend, ExoClusterBackend)
        assert brain._backend.base_url == "http://127.0.0.1:52415"

    def test_the_constructed_backend_carries_the_posture_and_the_receipt(self):
        """Without both, the endpoint gate above is unreachable code: no config
        means fail-closed on every remote cluster, and no hook means a LAN or
        remote request that leaves no trace on the wearer's receipt."""
        brain = Brain(tempfile.mkdtemp())
        brain.config.model = "exo"
        brain._wire_model()
        assert brain._backend.config is brain.config
        assert brain._backend._on_egress == brain._note_model_egress

    def test_the_synthesizer_is_wired_to_the_cluster(self):
        """`make_synthesizer` is what turns retrieved passages into prose. A
        tier with a backend and no synthesizer answers like keyword mode while
        the panel reports a model is loaded."""
        brain = Brain(tempfile.mkdtemp())
        brain.config.model = "exo"
        brain._wire_model()
        assert brain.index.synthesizer is not None
        brain._backend._post = lambda u, p: {"text": "from the cluster"}
        assert brain.index.synthesizer("q", [("n", "t")]) == "from the cluster"

    def test_the_config_carries_an_endpoint_and_a_model_name(self):
        c = BrainConfig()
        assert c.exo_url == DEFAULT_EXO_URL
        assert c.exo_model == DEFAULT_EXO_MODEL

    def test_the_configured_model_name_reaches_the_payload(self):
        """A model field the request never sends is a setting that does nothing.
        exo routes by model name, so this is the whole difference between the
        3B and the 70B the cluster exists to run."""
        brain = Brain(tempfile.mkdtemp())
        brain.config.model = "exo"
        brain.config.exo_model = "llama-3.3-70b"
        brain._wire_model()
        sent = []
        brain._backend._post = lambda u, p: sent.append(p) or {"text": "x"}
        brain._backend.chat("hi")
        assert sent and sent[0]["model"] == "llama-3.3-70b", sent

    def test_embeddings_stay_off_on_this_tier(self):
        """exo serves no embeddings endpoint. Wiring one that 404s would degrade
        recall to keyword while the panel said embeddings were on — the same
        class of lie as a false green."""
        brain = Brain(tempfile.mkdtemp())
        brain.config.model = "exo"
        brain.config.semantic_search = True      # asked for, and still refused
        brain._wire_model()
        assert brain.index.embedder is None

    def test_switching_away_replaces_the_backend(self):
        """`_wire_model` is called on every config save. A branch that only ever
        adds leaves the previous tier answering after the wearer switched off."""
        brain = Brain(tempfile.mkdtemp())
        brain.config.model = "exo"
        brain._wire_model()
        assert isinstance(brain._backend, ExoClusterBackend)
        brain.config.model = "keyword"
        brain._wire_model()
        assert brain._backend is None

    def test_the_endpoint_is_ssrf_checked_on_save(self):
        """`exo_url` is wearer-supplied, so a patch pointing it at link-local /
        metadata space must be reverted rather than persisted."""
        brain = Brain(tempfile.mkdtemp())
        brain.apply_config({"model": "exo", "exo_url": "http://169.254.169.254"})
        assert brain.config.exo_url != "http://169.254.169.254"

    def test_both_fields_round_trip_through_apply_config(self):
        brain = Brain(tempfile.mkdtemp())
        brain.apply_config({"model": "exo", "exo_url": "http://10.0.0.4:52415",
                            "exo_model": "qwen2.5-32b"})
        assert brain.config.exo_url == "http://10.0.0.4:52415"
        assert brain.config.exo_model == "qwen2.5-32b"
        assert isinstance(brain._backend, ExoClusterBackend)
        assert brain._backend.model == "qwen2.5-32b"


class TestTheTierIsReachableFromTheSurface:
    """A config field nothing can set is the gap one layer up."""

    def test_the_panel_offers_the_tier_in_the_model_picker(self):
        src = PANEL.read_text(encoding="utf-8")
        assert "pickModel('exo')" in src
        assert 'data-m="exo"' in src

    def test_the_panel_saves_both_fields(self):
        src = PANEL.read_text(encoding="utf-8")
        i = src.index("async function saveModel")
        body = src[i:i + 600]
        assert "exo_url:$(\"xurl\").value" in body
        assert "exo_model:$(\"xmodel\").value" in body

    def test_the_panel_loads_the_saved_values_back(self):
        """Without this the fields render empty every reload and a Save wipes
        the endpoint the wearer set."""
        src = PANEL.read_text(encoding="utf-8")
        assert '$("xurl").value=c.config.exo_url' in src
        assert '$("xmodel").value=c.config.exo_model' in src

    def test_the_saved_tier_survives_a_reload(self):
        """`load()` whitelists the model values it will restore; a tier missing
        from that list silently reverts the segment to Keyword."""
        src = PANEL.read_text(encoding="utf-8")
        i = src.index('const mm=[')
        assert '"exo"' in src[i:i + 120], src[i:i + 120]

    def test_the_locality_warning_is_shown_before_saving(self):
        """The panel mirrors the server's verdict rather than describing it, so
        the two cannot disagree about what an address IS."""
        src = PANEL.read_text(encoding="utf-8")
        assert "function renderExoWarn" in src
        i = src.index("function renderExoWarn")
        body = src[i:i + 1600]
        assert "isLocalUrl(" in body
        assert "egress" in body

    def test_the_status_row_names_the_tier_it_is_running(self):
        """It read "Keyword · active" for every non-Ollama choice, which told a
        wearer on their own API brain that no model was loaded."""
        src = PANEL.read_text(encoding="utf-8")
        assert 'exo cluster · active' in src
        assert 'Your API · active' in src


class TestTheCapabilityCatalogueAgrees:

    def test_the_seam_names_the_file_the_brain_now_constructs(self):
        from dreamlayer import capabilities as C
        cap = next(c for c in C.CAPABILITIES if c.key == "exo_cluster")
        assert cap.seam == "ai_brain/exo_cluster.py"
        assert cap.kind == "service"

    def test_it_is_not_declared_dormant(self):
        """It never was, which is exactly why it mattered: `_NOT_WIRED` would
        have told the wearer the truth. It reported "external" instead — honest
        about being a service, silent about nothing being able to use it."""
        from dreamlayer import capabilities as C
        assert "exo_cluster" not in C._NOT_WIRED
