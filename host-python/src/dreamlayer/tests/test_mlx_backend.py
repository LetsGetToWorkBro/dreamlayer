"""MLX seams (Apple-Silicon-native): the LLM answer backend and the vision
classifier. MLX isn't installable off macOS, so these verify the availability
gating, the degradation contract, and the adapter mapping via injected
generators — no MLX runtime required."""
from dreamlayer.ai_brain.mlx_backend import MLXBackend
from dreamlayer.object_lens.classify_backends import (
    MLXVisionClassifier, MoondreamClassifier, ClipClassifier, YoloClassifier,
    HeuristicVisionClassifier, default_classifier,
)


class TestMLXLLMBackend:
    def test_unavailable_chat_returns_empty(self):
        # no mlx-lm here → available False → chat declines with ""
        assert MLXBackend.available is False
        assert MLXBackend(config=None).chat("hello") == ""

    def test_injected_generate_maps_to_chat(self):
        seen = {}
        def gen(model, tok, prompt, max_tokens):
            seen["prompt"] = prompt
            seen["max"] = max_tokens
            return "  a written answer  "
        b = MLXBackend(config=None, _generate=gen)
        assert b.chat("summarize my week") == "a written answer"
        assert seen["prompt"] == "summarize my week"

    def test_generate_error_degrades(self):
        def boom(*a): raise RuntimeError("no metal")
        assert MLXBackend(config=None, _generate=boom).chat("x") == ""

    def test_vision_and_embed_decline(self):
        b = MLXBackend(config=None, _generate=lambda *a: "x")
        assert b.vision("cat", None, "name") == ""
        assert b.embed("text") == []

    def test_make_synthesizer_uses_chat(self):
        from dreamlayer.ai_brain.server.backends import make_synthesizer
        b = MLXBackend(config=None,
                       _generate=lambda m, t, prompt, mx: "SYNTH:" + prompt[:4])
        synth = make_synthesizer(b)
        out = synth("q?", [("note", "body")])
        assert out.startswith("SYNTH:")


class TestMLXWiringFallback:
    def test_model_mlx_falls_back_to_ollama_off_apple(self, tmp_path):
        # config.model == "mlx" but MLX unavailable here → Ollama backend wired,
        # synthesizer present, no crash
        from dreamlayer.ai_brain.server import Brain
        brain = Brain(tmp_path)
        brain.config.model = "mlx"
        brain._wire_model()
        from dreamlayer.ai_brain.server.backends import OllamaBackend
        assert isinstance(brain._backend, OllamaBackend)
        assert brain.index.synthesizer is not None


class TestMLXVisionClassifier:
    def test_unavailable_returns_none(self):
        assert MLXVisionClassifier.available is False
        assert MLXVisionClassifier()(object()) is None

    def test_injected_generate_maps_to_label(self):
        clf = MLXVisionClassifier(_generate=lambda m, p, prompt, frame: "Monstera.")
        assert clf(object()) == ("monstera", 0.6)

    def test_empty_answer_is_none(self):
        clf = MLXVisionClassifier(_generate=lambda *a: "   ")
        assert clf(object()) is None

    def test_infer_error_is_none(self):
        def boom(*a): raise RuntimeError("no metal")
        assert MLXVisionClassifier(_generate=boom)(object()) is None

    def test_ladder_prefers_mlx_over_moondream(self, monkeypatch):
        monkeypatch.setattr(YoloClassifier, "available", False)
        monkeypatch.setattr(MLXVisionClassifier, "available", True)
        monkeypatch.setattr(MoondreamClassifier, "available", True)
        monkeypatch.setattr(ClipClassifier, "available", True)
        assert isinstance(default_classifier(labels=["x"]), MLXVisionClassifier)

    def test_ladder_falls_to_heuristic_when_none(self, monkeypatch):
        for cls in (YoloClassifier, MLXVisionClassifier, MoondreamClassifier,
                    ClipClassifier):
            monkeypatch.setattr(cls, "available", False)
        assert isinstance(default_classifier(), HeuristicVisionClassifier)
