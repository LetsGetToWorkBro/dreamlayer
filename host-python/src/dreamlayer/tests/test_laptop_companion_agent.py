"""test_laptop_companion_agent.py — the real laptop agent, over real HTTP.

Proves the runnable companion (laptop-companion/dreamlayer_companion.py)
reads context and serves the DreamLayer contract, and that the phone-side
client (object_lens.integrations.laptop_data_source) talks to it."""
from __future__ import annotations

import importlib.util
import threading
import time
from pathlib import Path

import pytest

from dreamlayer.object_lens.integrations import laptop_data_source

AGENT_PATH = Path(__file__).resolve().parents[4] / "laptop-companion" \
    / "dreamlayer_companion.py"


def _load_agent():
    spec = importlib.util.spec_from_file_location("dl_companion", AGENT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


agent = _load_agent()


def _home_with_files(tmp_path):
    docs = tmp_path / "Documents"
    docs.mkdir()
    (docs / ".hidden").write_text("x")            # hidden: ignored
    for i, name in enumerate(["old.txt", "mid.md", "new.pdf"]):
        f = docs / name
        f.write_text("content")
        # stagger mtimes so ordering is deterministic (new.pdf newest)
        import os
        os.utime(f, (1000 + i, 1000 + i))
    return tmp_path


class TestReaders:
    def test_recent_files_newest_first_and_skips_hidden(self, tmp_path):
        home = _home_with_files(tmp_path)
        got = agent.recent_files(home=home)
        assert got[0] == "new.pdf"                # newest by mtime
        assert ".hidden" not in got

    def test_build_context_shape(self, tmp_path):
        ctx = agent.build_context(home=_home_with_files(tmp_path))
        assert "recent_files" in ctx and "hostname" in ctx
        assert isinstance(ctx["recent_files"], list)

    def test_battery_is_int_or_none(self):
        b = agent.battery_percent()
        assert b is None or (isinstance(b, int) and 0 <= b <= 100)


class TestServeAndFetch:
    def _serve(self, token, home):
        server = agent.make_server(
            token, "127.0.0.1", 0,
            context_fn=lambda: agent.build_context(home=home))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = server.server_address[1]
        return server, f"http://127.0.0.1:{port}"

    def test_phone_client_fetches_from_the_real_agent(self, tmp_path):
        server, url = self._serve("rune-birch", _home_with_files(tmp_path))
        try:
            fetch = laptop_data_source(url, token="rune-birch")
            ctx = fetch()
            assert ctx["recent_files"][0] == "new.pdf"
            assert "hostname" in ctx
        finally:
            server.shutdown(); server.server_close()

    def test_wrong_token_rejected(self, tmp_path):
        server, url = self._serve("right", _home_with_files(tmp_path))
        try:
            with pytest.raises(Exception):
                laptop_data_source(url, token="wrong")()
        finally:
            server.shutdown(); server.server_close()

    def test_lan_bind_without_token_is_refused(self):
        # main() must refuse to expose files on the LAN with no token
        assert agent.main(["--host", "0.0.0.0", "--port", "0"]) == 2
