"""Live Lens short-code redeem — the typeable fallback for a phone that can't
scan the QR. It hands out the Brain token over the LAN, so the tests hold the
line on every guard: single active code, short TTL, single-use, wrong-guess
doesn't consume, brute-force locked out on the shared limiter, and the endpoint
still sits behind the CSRF + rebind guards even though it's pre-auth.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request


from dreamlayer.ai_brain.server import Brain, BrainConfig, make_brain_server
import dreamlayer.ai_brain.server.server as srv


# --- the vault, in isolation --------------------------------------------------

class TestVault:
    def test_issue_then_redeem_returns_token_once(self):
        v = srv._LiveCodeVault()
        code = v.issue("SECRET")
        assert len(code) == srv._LIVE_CODE_DIGITS and code.isdigit()
        assert v.redeem(code) == "SECRET"
        assert v.redeem(code) is None            # single-use

    def test_wrong_guess_does_not_consume_the_live_code(self):
        v = srv._LiveCodeVault()
        code = v.issue("SECRET")
        assert v.redeem("00000000" if code != "00000000" else "11111111") is None
        assert v.redeem(code) == "SECRET"        # the real code still works

    def test_expiry(self):
        t = [1000.0]
        v = srv._LiveCodeVault(now_fn=lambda: t[0])
        code = v.issue("SECRET", ttl=300.0)
        t[0] += 301.0
        assert v.redeem(code) is None

    def test_reissue_voids_the_old_code(self):
        v = srv._LiveCodeVault()
        old = v.issue("SECRET")
        new = v.issue("SECRET")
        # (astronomically unlikely to collide, but guard the intent)
        if old != new:
            assert v.redeem(old) is None
        assert v.redeem(new) == "SECRET"

    def test_empty_and_nonstr_are_rejected(self):
        v = srv._LiveCodeVault()
        v.issue("SECRET")
        assert v.redeem("") is None
        assert v.redeem(None) is None            # type: ignore[arg-type]


# --- the endpoint, over a live server ----------------------------------------

class _Live:
    def __init__(self, tmp_path, token="tok"):
        cfg = tmp_path / "cfg"; cfg.mkdir()
        BrainConfig(token=token).save(cfg)
        self.brain = Brain(cfg)
        self.server = make_brain_server(self.brain, "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def stop(self):
        self.server.shutdown(); self.server.server_close()

    def _mint_code(self):
        """Pull a real code the way the panel does — an authed local GET."""
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(
            self.url + "/dreamlayer/live/link",
            headers={"X-DreamLayer-Token": self.brain.config.token})
        with opener.open(req, timeout=5) as r:
            return json.loads(r.read())["code"]

    def _redeem(self, code, origin=None):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        headers = {"Content-Type": "application/json"}
        if origin:
            headers["Origin"] = origin
        req = urllib.request.Request(
            self.url + "/dreamlayer/live/redeem",
            data=json.dumps({"code": code}).encode(), headers=headers, method="POST")
        try:
            with opener.open(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())


class TestRedeemEndpoint:
    def test_link_carries_a_code_and_it_redeems_the_token(self, tmp_path):
        lb = _Live(tmp_path)
        try:
            code = lb._mint_code()
            assert code and code.isdigit()
            status, body = lb._redeem(code)
            assert status == 200
            assert body["token"] == "tok"         # the real Brain token, handed out
        finally:
            lb.stop()

    def test_wrong_code_is_401_and_never_leaks_the_token(self, tmp_path):
        lb = _Live(tmp_path)
        try:
            lb._mint_code()
            status, body = lb._redeem("99999999")
            assert status in (401, 429)
            assert "token" not in body
        finally:
            lb.stop()

    def test_redeem_is_pre_auth_but_behind_csrf(self, tmp_path):
        """No token needed to redeem (that's the point), but a cross-origin
        Origin is still refused by the shared CSRF guard."""
        lb = _Live(tmp_path)
        try:
            code = lb._mint_code()
            status, body = lb._redeem(code, origin="http://evil.example")
            assert status == 403
            assert "token" not in body
        finally:
            lb.stop()

    def test_brute_force_locks_out(self, tmp_path):
        """The shared auth limiter (10 tries / 60 s) must lock out a grinder
        before the 1e8 space is meaningfully explored."""
        lb = _Live(tmp_path)
        try:
            lb._mint_code()
            saw_lockout = False
            for _ in range(25):
                status, _ = lb._redeem("00000000")
                if status == 429:
                    saw_lockout = True
                    break
            assert saw_lockout, "grinder was never locked out"
        finally:
            lb.stop()

    def test_lockout_blocks_even_a_correct_code(self, tmp_path):
        """Once locked out, even the right code is refused — the lockout is the
        point (a correct guess arriving mid-lockout must not slip through)."""
        lb = _Live(tmp_path)
        try:
            code = lb._mint_code()
            for _ in range(15):
                lb._redeem("00000000")
            status, body = lb._redeem(code)
            assert status == 429
            assert "token" not in body
        finally:
            lb.stop()


class TestTokenlessBrainOffersNoCode:
    def test_no_token_no_code(self, tmp_path):
        """A tokenless (loopback-only) Brain has nothing to hand out, so the
        link carries no code."""
        lb = _Live(tmp_path, token="")
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(lb.url + "/dreamlayer/live/link", timeout=5) as r:
                data = json.loads(r.read())
            assert data.get("code", "") == ""
        finally:
            lb.stop()
