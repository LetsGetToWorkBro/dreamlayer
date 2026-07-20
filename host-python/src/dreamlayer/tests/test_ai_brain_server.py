"""test_ai_brain_server.py — the Brain app: config, index, server, clients.

Phases 2-4 plumbing + the config layer: store round-trips, the folder index,
the Ollama backend seam, the server over real localhost HTTP (config,
folders, drag-drop upload, ask, explain, history, token gate, panel), the
phone-side remote clients + router wiring, and the opt-in cloud tier."""
from __future__ import annotations

import json
import tempfile
import threading
import urllib.request
from pathlib import Path


from dreamlayer.ai_brain import (
    BrainRouter, RemoteKnowledgeBrain, connect_brain,
    CloudKnowledgeBrain, CloudVisionBrain,
)
from dreamlayer.ai_brain.server import (
    BrainConfig, QueryHistory, FileIndex, Brain, make_brain_server,
    OllamaBackend, vision_answer,
)


def _post(url, payload, headers=None):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json",
                                          **(headers or {})})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=5) as r:
        return r.status, json.loads(r.read().decode())


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=5) as r:
            ct = r.headers.get("Content-Type", "")
            body = r.read().decode()
            return r.status, (json.loads(body) if "json" in ct else body)
    except urllib.error.HTTPError as e:
        return e.code, None


# ---------------------------------------------------------------------------
# Store + index
# ---------------------------------------------------------------------------

class TestStore:
    def test_config_round_trip_and_folders(self, tmp_path):
        c = BrainConfig()
        d = tmp_path / "watched"; d.mkdir()
        assert c.add_folder(str(d)) and not c.add_folder(str(d))
        c.model = "ollama"
        c.save(tmp_path)
        back = BrainConfig.load(tmp_path)
        assert back.folders == [str(d)] and back.model == "ollama"

    def test_add_folder_allow_list_rejects_sensitive_paths(self, tmp_path):
        # SECURITY (revert-failing): add_folder must default-deny anything
        # outside the user's home / temp trees. Before the allow-list, a token
        # holder could point the Brain at /etc, /, or another user's home.
        import os
        from pathlib import Path
        c = BrainConfig()
        # a legit directory under the user's home is accepted
        home_sub = tempfile.mkdtemp(dir=str(Path.home()))
        try:
            assert c.add_folder(home_sub) is True
            assert home_sub in c.folders
        finally:
            os.rmdir(home_sub)
        # sensitive / out-of-home paths are refused and never stored
        for bad in ("/etc", "/", "/usr", "/home/someone-else", "/var/root"):
            assert c.add_folder(bad) is False
            assert bad not in c.folders
            assert str(Path(bad).expanduser()) not in c.folders

    def test_load_sanitizes_disallowed_folders(self, tmp_path):
        # SECURITY (revert-failing, refute-remediation 2026-07): a hand-edited
        # or pre-remediation config file must not reintroduce a disallowed
        # watched folder on load — add_folder is not the only writer.
        from dreamlayer.ai_brain.server.store import CONFIG_FILE
        good = tmp_path / "ok"; good.mkdir()
        (tmp_path / CONFIG_FILE).write_text(
            json.dumps({"folders": ["/etc", str(good)]}))
        cfg = BrainConfig.load(tmp_path)
        assert "/etc" not in cfg.folders
        assert str(good) in cfg.folders

    def test_reindex_skips_disallowed_folder_at_walk_sink(self, tmp_path, monkeypatch):
        # SECURITY (revert-failing): even if a disallowed path reaches
        # config.folders by ANY route (backup restore, legacy file, TOCTOU),
        # the index walk must refuse to read it. A real indexable file in a dir
        # forced disallowed proves the guard is at the walk sink, not vacuous.
        import dreamlayer.ai_brain.server.index as idxmod
        d = tmp_path / "secret"; d.mkdir()
        (d / "leak.txt").write_text("TOPSECRET passage content")
        cfg = BrainConfig()
        cfg.folders = [str(d)]
        monkeypatch.setattr(idxmod, "_is_allowed_root", lambda p: False)
        idx = FileIndex(cfg)
        idx.reindex()
        assert idx._passages == []      # walk sink refused the disallowed folder
        assert all("TOPSECRET" not in passage for _, passage in idx._passages)

    def test_import_backup_filters_disallowed_folders(self, tmp_path):
        # SECURITY (revert-failing): the CONFIRMED bypass — import_backup wrote
        # config.folders straight from request data with no allow-list.
        b = Brain(tmp_path)
        b.import_backup({"config": {"folders": ["/etc"]}})
        assert "/etc" not in b.config.folders

    def test_public_hides_token(self):
        c = BrainConfig(token="secret")
        assert c.public()["token"] == "set"

    def test_history_records_and_reads_newest_first(self, tmp_path):
        h = QueryHistory(tmp_path)
        h.add("q1", "a1", "laptop", ["f1"], ts=1)
        h.add("q2", "a2", "cloud", [], ts=2)
        items = h.recent(10)
        assert items[0]["query"] == "q2" and items[1]["query"] == "q1"


class TestIndex:
    def _folder(self, tmp_path):
        d = tmp_path / "notes"
        d.mkdir()
        (d / "lease.md").write_text("Rent is 2400 per month.\n\n"
                                    "The lease ends in June 2026.")
        (d / "marcus.txt").write_text("Marcus owes me the signed contract.")
        (d / "photo.jpg").write_bytes(b"\xff\xd8\xff")     # non-text: ignored
        return d

    def test_reindex_counts_text_files(self, tmp_path):
        cfg = BrainConfig(folders=[str(self._folder(tmp_path))])
        idx = FileIndex(cfg)
        stats = idx.reindex()
        assert stats["files"] == 2                 # jpg skipped

    def test_ask_returns_passage_and_source(self, tmp_path):
        cfg = BrainConfig(folders=[str(self._folder(tmp_path))])
        idx = FileIndex(cfg); idx.reindex()
        ans = idx.ask("how much is the rent")
        assert "2400" in ans.text and ans.sources == ["lease.md"]

    def test_ask_no_match(self, tmp_path):
        cfg = BrainConfig(folders=[str(self._folder(tmp_path))])
        idx = FileIndex(cfg); idx.reindex()
        assert idx.ask("airspeed of a swallow") is None

    def test_synthesizer_is_used_when_present(self, tmp_path):
        cfg = BrainConfig(folders=[str(self._folder(tmp_path))])
        idx = FileIndex(cfg, synthesizer=lambda q, ps: "SYNTHESISED")
        idx.reindex()
        assert idx.ask("rent").text == "SYNTHESISED"


class TestOllamaBackend:
    def test_chat_and_vision_via_mock_transport(self):
        posts = []
        def http_post(url, payload):
            posts.append((url, payload))
            return {"response": "a mock answer"}
        cfg = BrainConfig(model="ollama")
        b = OllamaBackend(cfg, http_post=http_post)
        assert b.chat("hi") == "a mock answer"
        assert b.vision("mug", None, "quick") == "a mock answer"
        assert posts[0][0].endswith("/api/generate")

    def test_vision_answer_none_without_backend(self):
        assert vision_answer(None, "mug", None, "quick") is None


# ---------------------------------------------------------------------------
# The server over real HTTP
# ---------------------------------------------------------------------------

class LiveBrain:
    def __init__(self, tmp_path, token="tok", folders=None):
        cfg_dir = tmp_path / "cfg"
        cfg_dir.mkdir()
        c = BrainConfig(token=token, folders=folders or [])
        c.save(cfg_dir)
        self.brain = Brain(cfg_dir)
        self.server = make_brain_server(self.brain, "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.h = {"X-DreamLayer-Token": token}

    def stop(self):
        self.server.shutdown(); self.server.server_close()


class TestServer:
    def test_panel_served_at_root(self, tmp_path):
        lb = LiveBrain(tmp_path)
        try:
            status, body = _get(lb.url + "/")
            assert status == 200 and "DreamLayer" in body and "Brain" in body
            # the People section now merges the glasses' social memory
            # (relation/notes/debts) with the dossier registry
            assert "/dreamlayer/social/people" in body and "met on Halo" in body
            # Juno lives on the panel: since the Platinum redesign she is the
            # pixel desk-accessory sprite served from the panel's own assets
            # (the photoreal juno.js mount is retired here; the script itself
            # is still served for the lens builder — see the test below)
            assert 'class="juno-hero"' in body and "data-juno" in body
            assert "/panel-assets/juno_da.webp" in body
        finally:
            lb.stop()

    def test_learn_catalog_is_current_and_true(self, tmp_path):
        """The Learn section runs the TRUE renderer: halo-sim.js is served as a
        panel asset (byte-identical to the site's copy), every `img` fallback
        in EXPLAINERS is a bundled file, and every `live` type is one the sim
        actually renders. A renamed/removed asset or a typo'd renderer type
        fails here, not in a user's modal."""
        import re
        import dreamlayer.ai_brain.server as server_mod
        assets = Path(server_mod.__file__).resolve().parent / "assets"
        sim = assets / "halo-sim.js"
        assert sim.is_file(), "halo-sim.js must ship inside the panel assets"
        # lockstep with the website's engine (repo checkouts only; the
        # installed package has no landing/ tree to compare against)
        site = Path(server_mod.__file__).resolve().parents[4].parent \
            / "landing" / "assets" / "sim" / "halo-sim.js"
        if site.is_file():
            assert sim.read_bytes() == site.read_bytes(), \
                "panel halo-sim.js drifted from landing/assets/sim/halo-sim.js"
        lb = LiveBrain(tmp_path)
        try:
            status, body = _get(lb.url + "/")
            assert status == 200
            assert '/panel-assets/halo-sim.js' in body
            # the sim script itself serves with a JS content-type
            req = urllib.request.Request(lb.url + "/panel-assets/halo-sim.js")
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req, timeout=5) as r:
                assert r.status == 200
                assert "javascript" in (r.headers.get("Content-Type") or "")
                assert b"Glass" in r.read()
            # every PNG fallback named in the catalog is really bundled
            block = body.split("const EXPLAINERS=[", 1)[1].split("];", 1)[0]
            imgs = re.findall(r'img:"([a-z0-9_.]+)"', block)
            assert len(imgs) >= 10
            for name in imgs:
                assert (assets / name).is_file(), f"missing panel asset {name}"
            # every live type is one the sim renders
            known = {"ready", "veil", "answer", "recall", "fact", "brief",
                     "toast", "object", "intro", "waypath", "keep", "rosetta"}
            lives = re.findall(r'live:\["([a-z_]+)"', block)
            assert len(lives) >= 10
            assert set(lives) <= known, f"unknown sim type: {set(lives) - known}"
            # the catalog covers the current library, not the 8-card past
            assert len(imgs) + len(lives) >= 25
            # the hidden layer stays wired (never listed in EXPLAINERS):
            # the lost-lens unlock plumbing in the panel, and the prism +
            # true-colors renderers in the sim engine
            assert "dl_prism" in body and "openPrism" in body
            assert "/dreamlayer/discoveries" in body
            sim_src = sim.read_text(encoding="utf-8")
            assert "_prism" in sim_src and "junocolors" in sim_src
            # discoveries: refused when unknown, kept when real, persistent
            try:
                code = _post(lb.url + "/dreamlayer/discoveries",
                             {"name": "nope"}, lb.h)[0]
            except urllib.error.HTTPError as e:
                code = e.code
            assert code == 400
            status, r = _post(lb.url + "/dreamlayer/discoveries",
                              {"name": "prism"}, lb.h)
            assert status == 200 and r["found"] == ["prism"]
            status, r = _get(lb.url + "/dreamlayer/discoveries", lb.h)
            assert status == 200 and r["found"] == ["prism"]
            reborn = Brain(lb.brain.cfg_dir)
            assert reborn.discoveries() == ["prism"]
        finally:
            lb.stop()

    def test_learn_catalog_grouped_by_category(self, tmp_path):
        """The Learn page reads as chapters, not one wall of chips: an XCATS
        list defines the categories (each with a one-line premise), every
        EXPLAINERS entry files itself under one of them, and the renderer
        emits per-category headers. Dropping the grouping fails here."""
        import re
        lb = LiveBrain(tmp_path)
        try:
            status, body = _get(lb.url + "/")
            assert status == 200
            # the categories exist, each with a title and a premise line
            assert "const XCATS=[" in body
            cats = body.split("const XCATS=[", 1)[1].split("];", 1)[0]
            cat_ids = re.findall(r'id:"([a-z]+)"', cats)
            assert len(cat_ids) >= 5, "Learn needs real chapters, not a token split"
            assert len(re.findall(r'\bb:"', cats)) == len(cat_ids), \
                "every category carries its one-line explainer"
            # every feature files itself under a defined category
            block = body.split("const EXPLAINERS=[", 1)[1].split("];", 1)[0]
            feat_cats = re.findall(r'\{c:"([a-z]+)"', block)
            n_feats = len(re.findall(r'\bt:"', block))
            assert len(feat_cats) == n_feats, "every EXPLAINERS entry needs a c: category"
            assert set(feat_cats) <= set(cat_ids), \
                f"unknown category: {set(feat_cats) - set(cat_ids)}"
            # ... and every category is actually used (no orphan headers)
            assert set(cat_ids) <= set(feat_cats), \
                f"empty category: {set(cat_ids) - set(feat_cats)}"
            # the renderer emits grouped markup, not one flat grid
            assert 'class="xcat"' in body and "xcat-t" in body and "xcat-b" in body
        finally:
            lb.stop()

    def test_panel_juno_speaks_on_click(self, tmp_path):
        """Clicking Juno's screen plays a bundled voice take (same clips the
        website and phone use). All six clips ship as panel assets, the click
        handler is wired, and mp3 serves with an audio content-type so the CSP's
        media-src 'self' path actually plays. No external audio, ever."""
        import dreamlayer.ai_brain.server as server_mod
        assets = Path(server_mod.__file__).resolve().parent / "assets"
        clips = ["juno_hey.mp3", "juno_hello.mp3", "juno_look.mp3",
                 "juno_watchout.mp3", "juno_based.mp3", "juno_uhokthen.mp3"]
        for c in clips:
            assert (assets / c).is_file(), f"missing bundled voice take {c}"
        lb = LiveBrain(tmp_path)
        try:
            status, body = _get(lb.url + "/")
            assert status == 200
            for c in clips:
                assert f"/panel-assets/{c}" in body, f"panel never references {c}"
            # the click wiring exists and only same-origin audio is played
            assert "Say hi to Juno" in body
            import re
            srcs = re.findall(r'"([^"]+\.mp3)"', body)
            assert srcs and all(s.startswith("/panel-assets/") for s in srcs), \
                f"non-bundled audio source: {[s for s in srcs if not s.startswith('/panel-assets/')]}"
            # mp3 serves as audio/mpeg (octet-stream would still play, but the
            # contract is a typed, cacheable, same-origin asset)
            req = urllib.request.Request(lb.url + "/panel-assets/juno_hey.mp3")
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req, timeout=5) as r:
                assert r.status == 200
                assert (r.headers.get("Content-Type") or "") == "audio/mpeg"
                assert len(r.read()) > 10_000
        finally:
            lb.stop()

    def test_panel_assets_all_covered_by_wheel_globs(self):
        """Every file type in the panel assets dir is matched by a pyproject
        package-data glob — otherwise the repo checkout serves it fine but the
        pip wheel silently ships without it (exactly how the Juno voice takes
        almost went missing). Repo checkouts only; the installed package has
        no pyproject.toml beside it."""
        import fnmatch
        import dreamlayer.ai_brain.server as server_mod
        assets = Path(server_mod.__file__).resolve().parent / "assets"
        pyproject = Path(server_mod.__file__).resolve().parents[4].parent \
            / "host-python" / "pyproject.toml"
        if not pyproject.is_file():
            import pytest
            pytest.skip("no pyproject beside the package (installed wheel)")
        try:
            import tomllib
        except ModuleNotFoundError:          # pragma: no cover — py<3.11
            import tomli as tomllib
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        globs = data["tool"]["setuptools"]["package-data"]["dreamlayer"]
        rels = [f"ai_brain/server/assets/{p.name}" for p in assets.iterdir()
                if p.is_file() and p.name != ".DS_Store"]
        assert rels, "assets dir unexpectedly empty"
        missing = [r for r in rels
                   if not any(fnmatch.fnmatch(r, g) for g in globs)]
        assert not missing, \
            f"panel assets not covered by any pyproject package-data glob: {missing}"

    def test_plugin_shots_bundled_same_origin(self, tmp_path):
        """The panel CSP pins img-src to 'self', so plugin screenshots must be
        bundled and served same-origin (a remote thumbnail would be blocked
        AND an egress). Every curated shot ships as plugshot_<name>.png,
        byte-identical to the website's copy, and the panel renders through
        the plugShot helper — never a remote URL."""
        import dreamlayer.ai_brain.server as server_mod
        assets = Path(server_mod.__file__).resolve().parent / "assets"
        names = ["air-drums", "currency-converter", "face-synth",
                 "filler-word-counter", "hud-reactions", "open-food-facts",
                 "open-library", "pokemon-price", "vinyl-oracle"]
        for n in names:
            assert (assets / f"plugshot_{n}.png").is_file(), f"missing shot {n}"
        site = Path(server_mod.__file__).resolve().parents[4].parent \
            / "landing" / "plugin-shots"
        if site.is_dir():
            for n in names:
                assert (assets / f"plugshot_{n}.png").read_bytes() == \
                    (site / f"{n}.png").read_bytes(), f"shot drifted: {n}"
        lb = LiveBrain(tmp_path)
        try:
            status, body = _get(lb.url + "/")
            assert status == 200
            assert "plugShot" in body and "/panel-assets/plugshot_" in body
            # the raw remote-screenshot src is gone from both render sites
            assert 'src="\'+esc(p.screenshot)' not in body
        finally:
            lb.stop()

    def test_juno_script_and_assets_serve(self, tmp_path):
        lb = LiveBrain(tmp_path)
        try:
            # the UMD sprite script — text, JS content-type
            status, body = _get(lb.url + "/dreamlayer/build/juno/juno.js")
            assert status == 200 and "Juno" in body and "mount" in body
            # a binary asset — raw read (can't decode as text)
            req = urllib.request.Request(lb.url + "/dreamlayer/build/juno/juno_idle.webp")
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req, timeout=5) as r:
                assert r.status == 200
                assert r.headers.get("Content-Type") == "image/webp"
                assert len(r.read()) > 100
            # path traversal and unknown extensions are refused
            assert _get(lb.url + "/dreamlayer/build/juno/..%2f..%2fserver.py")[0] == 404
            assert _get(lb.url + "/dreamlayer/build/juno/secrets.env")[0] == 404
        finally:
            lb.stop()

    def test_token_required_for_api(self, tmp_path):
        lb = LiveBrain(tmp_path)
        try:
            assert _get(lb.url + "/dreamlayer/config")[0] == 401   # no token
            assert _get(lb.url + "/dreamlayer/config", lb.h)[0] == 200
        finally:
            lb.stop()

    def test_add_folder_and_upload_then_ask(self, tmp_path):
        watch = tmp_path / "watched"; watch.mkdir()
        lb = LiveBrain(tmp_path)
        try:
            # add the folder via the API
            _post(lb.url + "/dreamlayer/folders",
                  {"action": "add", "path": str(watch)}, lb.h)
            # drag-drop a file into it
            up = (lb.url + "/dreamlayer/upload?folder="
                  + urllib.request.quote(str(watch)) + "&name=lease.md")
            req = urllib.request.Request(
                up, data=b"Rent is 2400 per month.", headers=lb.h)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req, timeout=5) as r:
                assert json.loads(r.read())["ok"] is True
            assert (watch / "lease.md").exists()
            # now ask about it
            status, ans = _post(lb.url + "/dreamlayer/brain/ask",
                                {"query": "how much is rent"}, lb.h)
            assert status == 200 and "2400" in ans["text"]
            # and it's in history
            _, hist = _get(lb.url + "/dreamlayer/history", lb.h)
            assert hist["items"][0]["query"] == "how much is rent"
        finally:
            lb.stop()

    def test_upload_rejects_unwatched_folder(self, tmp_path):
        lb = LiveBrain(tmp_path)
        try:
            up = lb.url + "/dreamlayer/upload?folder=/etc&name=evil.txt"
            req = urllib.request.Request(up, data=b"x", headers=lb.h)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            try:
                with opener.open(req, timeout=5) as r:
                    assert False, "unwatched write should be rejected"
            except urllib.error.HTTPError as e:
                assert e.code == 400 and json.loads(e.read())["ok"] is False
            assert not (Path("/etc") / "evil.txt").exists()
        finally:
            lb.stop()

    def test_explain_empty_without_vision_model(self, tmp_path):
        lb = LiveBrain(tmp_path)
        try:
            _, ans = _post(lb.url + "/dreamlayer/brain/explain",
                           {"label": "mug", "want": "quick"}, lb.h)
            assert ans["text"] == ""       # keyword model has no vision tier
        finally:
            lb.stop()


# ---------------------------------------------------------------------------
# Phone-side clients + router + cloud tier
# ---------------------------------------------------------------------------

class TestRemoteAndRouter:
    def test_remote_knowledge_through_router(self, tmp_path):
        watch = tmp_path / "w"; watch.mkdir()
        (watch / "lease.md").write_text("Rent is 2400 per month.")
        lb = LiveBrain(tmp_path, folders=[str(watch)])
        try:
            router = BrainRouter()
            connect_brain(router, lb.url, token="tok")
            ans = router.ask("how much is rent")
            assert ans is not None and "2400" in ans.text and ans.tier == "laptop"
        finally:
            lb.stop()

    def test_remote_returns_none_on_bad_token(self, tmp_path):
        lb = LiveBrain(tmp_path, folders=[])
        try:
            rk = RemoteKnowledgeBrain(lb.url, token="wrong")
            assert rk.ask("anything") is None      # 401 -> None, not a crash
        finally:
            lb.stop()


class TestCloudTier:
    def _router(self):
        r = BrainRouter()
        r.add_knowledge(CloudKnowledgeBrain(lambda q: f"cloud says: {q}"))
        r.add_vision(CloudVisionBrain(lambda f, l, w: f"cloud sees a {l}"))
        return r

    def test_cloud_gated_off_by_default(self):
        assert self._router().ask("hi") is None

    def test_cloud_answers_when_opted_in(self):
        r = self._router()
        r.opt_in_cloud(True)
        assert "cloud says" in r.ask("hi").text
        assert r.explain(None, "mug").tier == "cloud"


class TestDiscoveriesHardening:
    """The hidden-layer discovery store, hardened after the 2026-07-20 refute
    pass: the LOAD path validates (not just add_discovery), and a non-object
    POST body can't crash the handler."""

    def test_load_keeps_only_known_names(self, tmp_path):
        # A hand-edited / attacker-planted discoveries.json injected arbitrary
        # strings straight into the set (and a mixed str/int set made
        # discoveries()'s sorted() an unhandled 500). Load now filters to known.
        cfg = tmp_path / "cfg"; cfg.mkdir()
        BrainConfig(token="tok").save(cfg)
        (cfg / "discoveries.json").write_text(
            json.dumps(["prism", "evil<script>", 1, "junocolors", "nope"]))
        b = Brain(cfg)
        assert b.discoveries() == ["junocolors", "prism"]   # junk dropped; sorted() safe

    def test_load_survives_a_non_list_file(self, tmp_path):
        cfg = tmp_path / "cfg"; cfg.mkdir()
        BrainConfig(token="tok").save(cfg)
        for junk in ("5", "null", "true", '{"prism": 1, "x": 2}', "not json at all"):
            (cfg / "discoveries.json").write_text(junk)
            b = Brain(cfg)                              # never raises
            assert set(b.discoveries()) <= {"prism", "junocolors"}

    def test_post_non_dict_body_is_a_clean_400_not_a_dropped_connection(self, tmp_path):
        # _body() could return a list/str/int for a non-object JSON body;
        # _post_discoveries did _body().get(...) → AttributeError → unhandled,
        # the worker dropped the connection with no response. _body() now coerces
        # a non-object to {}, so this is a clean, counted 400.
        lb = LiveBrain(tmp_path)
        try:
            data = json.dumps([1, 2, 3]).encode()
            req = urllib.request.Request(
                lb.url + "/dreamlayer/discoveries", data=data,
                headers={"Content-Type": "application/json", **lb.h})
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            try:
                status = opener.open(req, timeout=5).status
            except urllib.error.HTTPError as e:
                status = e.code                          # 400 = handled, not dropped
            assert status == 400
        finally:
            lb.stop()
