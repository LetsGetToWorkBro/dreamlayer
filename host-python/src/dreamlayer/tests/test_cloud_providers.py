"""Multi-provider cloud adapters — request shaping + response parsing.

Pure unit tests (no network): assert each provider's wire format is built and
parsed correctly, and that Ollama-local needs no key.
"""
from dreamlayer.ai_brain.server import backends as be
from dreamlayer.ai_brain.server.store import BrainConfig


def _cfg(**kw):
    return BrainConfig(**kw)


class TestBuildRequest:
    def test_openai_default(self):
        wire, url, body, headers = be._build_cloud_request(
            _cfg(cloud_provider="openai", cloud_api_key="sk-x",
                 cloud_model="gpt-4o-mini"), "hi")
        assert wire == "openai"
        assert url == "https://api.openai.com/v1/chat/completions"
        assert body["model"] == "gpt-4o-mini"
        assert body["messages"][0]["content"] == "hi"
        assert headers["Authorization"] == "Bearer sk-x"

    def test_anthropic_native(self):
        wire, url, body, headers = be._build_cloud_request(
            _cfg(cloud_provider="anthropic", cloud_base_url="https://api.anthropic.com",
                 cloud_api_key="sk-ant", cloud_model="claude-3-5-haiku-latest"), "hi")
        assert wire == "anthropic"
        assert url.endswith("/v1/messages")
        assert headers["x-api-key"] == "sk-ant"
        assert headers["anthropic-version"] == "2023-06-01"
        assert "Authorization" not in headers      # Anthropic uses x-api-key
        assert body["max_tokens"] >= 1

    def test_gemini_native(self):
        wire, url, body, headers = be._build_cloud_request(
            _cfg(cloud_provider="gemini",
                 cloud_base_url="https://generativelanguage.googleapis.com",
                 cloud_api_key="k&y", cloud_model="gemini-1.5-flash"), "hi")
        assert wire == "gemini"
        assert "/v1beta/models/gemini-1.5-flash:generateContent" in url
        assert "key=k%26y" in url                  # key is URL-encoded
        assert body["contents"][0]["parts"][0]["text"] == "hi"

    def test_ollama_local_needs_no_key(self):
        wire, url, body, headers = be._build_cloud_request(
            _cfg(cloud_provider="ollama", cloud_base_url="http://localhost:11434",
                 cloud_api_key="", cloud_model="llama3.2"), "hi")
        assert wire == "openai"                     # OpenAI-compatible wire
        assert url == "http://localhost:11434/v1/chat/completions"
        assert "Authorization" not in headers       # no key sent

    def test_openrouter_is_openai_compatible(self):
        wire, url, _, headers = be._build_cloud_request(
            _cfg(cloud_provider="openrouter", cloud_base_url="https://openrouter.ai/api",
                 cloud_api_key="or-1", cloud_model="openai/gpt-4o-mini"), "hi")
        assert wire == "openai"
        assert url == "https://openrouter.ai/api/v1/chat/completions"
        assert headers["Authorization"] == "Bearer or-1"

    def test_groq_preset_is_openai_compatible(self):
        # Groq's /openai/v1 base already carries /v1, so the adapter must NOT
        # double it — POST lands on /openai/v1/chat/completions, not /v1/v1/….
        p = be.PROVIDER_PRESETS["groq"]
        wire, url, _, headers = be._build_cloud_request(
            _cfg(cloud_provider="groq", cloud_base_url=p["base_url"],
                 cloud_api_key="gsk-1", cloud_model=p["model"]), "hi")
        assert wire == "openai"
        assert url == "https://api.groq.com/openai/v1/chat/completions"
        assert headers["Authorization"] == "Bearer gsk-1"

    def test_together_preset_is_openai_compatible(self):
        p = be.PROVIDER_PRESETS["together"]
        wire, url, _, headers = be._build_cloud_request(
            _cfg(cloud_provider="together", cloud_base_url=p["base_url"],
                 cloud_api_key="tg-1", cloud_model=p["model"]), "hi")
        assert wire == "openai"
        assert url == "https://api.together.xyz/v1/chat/completions"
        assert headers["Authorization"] == "Bearer tg-1"

    def test_deepseek_preset_is_openai_compatible(self):
        # DeepSeek's base is the host root (like OpenAI); the adapter appends
        # /v1/chat/completions, which DeepSeek accepts as a compat alias.
        p = be.PROVIDER_PRESETS["deepseek"]
        wire, url, _, headers = be._build_cloud_request(
            _cfg(cloud_provider="deepseek", cloud_base_url=p["base_url"],
                 cloud_api_key="ds-1", cloud_model=p["model"]), "hi")
        assert wire == "openai"
        assert url == "https://api.deepseek.com/v1/chat/completions"
        assert headers["Authorization"] == "Bearer ds-1"


class TestParseResponse:
    def test_openai_shape(self):
        d = {"choices": [{"message": {"content": " hello "}}]}
        assert be._parse_cloud_response("openai", d) == "hello"

    def test_anthropic_shape(self):
        d = {"content": [{"type": "text", "text": "hi "}, {"type": "text", "text": "there"}]}
        assert be._parse_cloud_response("anthropic", d) == "hi there"

    def test_gemini_shape(self):
        d = {"candidates": [{"content": {"parts": [{"text": "answer"}]}}]}
        assert be._parse_cloud_response("gemini", d) == "answer"

    def test_empty_shapes_are_safe(self):
        assert be._parse_cloud_response("openai", {}) == ""
        assert be._parse_cloud_response("anthropic", {}) == ""
        assert be._parse_cloud_response("gemini", {}) == ""


class TestCloudReady:
    def test_ollama_ready_without_key(self):
        c = BrainConfig(cloud_provider="ollama", cloud_model="llama3.2",
                        cloud_api_key="", cloud_enabled=True)
        assert c.cloud_ready() is True

    def test_openai_needs_key(self):
        assert BrainConfig(cloud_provider="openai", cloud_model="gpt-4o-mini",
                           cloud_api_key="", cloud_enabled=True).cloud_ready() is False
        assert BrainConfig(cloud_provider="openai", cloud_model="gpt-4o-mini",
                           cloud_api_key="k", cloud_enabled=True).cloud_ready() is True

    def test_lan_only_shuts_even_ollama(self):
        c = BrainConfig(cloud_provider="ollama", cloud_model="llama3.2",
                        network_mode="lan_only")
        assert c.cloud_ready() is False


def test_cloud_chat_injected_still_works():
    # The injected-http_post path (used across existing tests) is unchanged.
    c = BrainConfig(cloud_provider="openai", cloud_model="m", cloud_api_key="k")
    out = be.cloud_chat(c, "q", http_post=lambda url, payload: {"text": "ok"})
    assert out == "ok"


# --- OpenAI-compatible provider presets (issue #389) -----------------------------
#
# Groq / Together / DeepSeek are one-click presets: pre-fill a base URL + model,
# speak the OpenAI wire, and require a key (remote → amber egress warning). Each
# lives in FOUR mirrored spots that must stay in sync — backends.PROVIDER_PRESETS,
# the panel's CPROV and APROV JS tables, and the two <select> option lists. These
# tests bite if any spot drifts.

# expected shape: base_url that the adapter must resolve to /…/chat/completions
_OPENAI_COMPAT_PRESETS = {
    "groq": ("Groq", "https://api.groq.com/openai/v1",
             "https://api.groq.com/openai/v1/chat/completions"),
    "together": ("Together AI", "https://api.together.xyz/v1",
                 "https://api.together.xyz/v1/chat/completions"),
    "deepseek": ("DeepSeek", "https://api.deepseek.com",
                 "https://api.deepseek.com/v1/chat/completions"),
}


class TestOpenAICompatPresets:
    def test_backends_presets_are_well_formed(self):
        for key, (label, base_url, expected_url) in _OPENAI_COMPAT_PRESETS.items():
            p = be.PROVIDER_PRESETS[key]
            assert p["label"] == label
            assert p["base_url"] == base_url
            assert p["wire"] == "openai"          # OpenAI wire, no new adapter
            assert p["needs_key"] is True         # remote → key field + egress warn
            assert p["model"]                     # a sensible default is pre-filled
            # the preset resolves to a real OpenAI chat-completions endpoint
            _, url, _, _ = be._build_cloud_request(
                _cfg(cloud_provider=key, cloud_base_url=p["base_url"],
                     cloud_api_key="k", cloud_model=p["model"]), "hi")
            assert url == expected_url

    def test_presets_are_remote_so_the_egress_warning_fires(self):
        # amber (remote), never green (on-device) — the privacy contract.
        for key in _OPENAI_COMPAT_PRESETS:
            assert be.is_local_endpoint(be.PROVIDER_PRESETS[key]["base_url"]) is False

    def test_panel_dropdowns_and_tables_mirror_backends(self):
        from dreamlayer.ai_brain.server.panel import render_panel
        html = render_panel(token="t")
        for key, (label, base_url, _url) in _OPENAI_COMPAT_PRESETS.items():
            p = be.PROVIDER_PRESETS[key]
            # both <select>s (cloud escalation + primary API brain) list it
            assert html.count(f'<option value="{key}">{label}</option>') == 2
            # both JS preset tables (CPROV + APROV) carry the same base + model,
            # so the dropdown pre-fills exactly what backends would build.
            entry = f'{key}:{{base:"{base_url}",model:"{p["model"]}",key:true}}'
            assert html.count(entry) == 2
