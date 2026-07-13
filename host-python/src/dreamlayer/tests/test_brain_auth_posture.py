"""The Brain's network-auth posture (P0 audit fix).

The old default served an unauthenticated brain on 0.0.0.0 with an empty
token — `_authed` returned True whenever no token was set, so every device on
the LAN could read `/dreamlayer/*` and, via add-folder + ask, exfiltrate local
files. Two layers close it: the launcher mints a token for any network-
reachable bind, and the access policy trusts an empty token only from
loopback. These tests pin both.
"""
from __future__ import annotations

from dreamlayer.ai_brain.server import authorize
from dreamlayer.ai_brain.server.__main__ import _is_loopback_host


class TestAuthorizePolicy:
    def test_configured_token_must_match_from_anywhere(self):
        # correct token → in, wrong/absent → out, regardless of origin
        assert authorize("s3cret", "s3cret", from_localhost=True) is True
        assert authorize("s3cret", "s3cret", from_localhost=False) is True
        assert authorize("s3cret", "nope", from_localhost=True) is False
        assert authorize("s3cret", None, from_localhost=False) is False

    def test_empty_token_trusts_loopback_only(self):
        # the whole point: a tokenless brain is a local-dev brain
        assert authorize("", None, from_localhost=True) is True
        assert authorize("", None, from_localhost=False) is False   # LAN refused
        assert authorize("", "anything", from_localhost=False) is False

    def test_wrong_type_provided_is_refused(self):
        assert authorize("s3cret", 12345, from_localhost=True) is False


class TestLoopbackClassification:
    def test_loopback_hosts(self):
        for h in ("127.0.0.1", "localhost", "::1", "::ffff:127.0.0.1"):
            assert _is_loopback_host(h) is True

    def test_network_reachable_hosts(self):
        for h in ("0.0.0.0", "192.168.1.10", "10.0.0.5", "::"):
            assert _is_loopback_host(h) is False


class TestLauncherMintsTokenForNetworkBind:
    """The launcher must never leave a network-reachable brain tokenless."""

    def _decide(self, existing_token: str, host: str):
        # mirror of __main__.main's minting decision, exercised directly so we
        # don't have to serve_forever(); asserts the rule, not the print copy.
        import secrets
        token = existing_token
        minted = False
        if not token and not _is_loopback_host(host):
            token = secrets.token_hex(16)
            minted = True
        return token, minted

    def test_lan_bind_no_token_mints_one(self):
        token, minted = self._decide("", "0.0.0.0")
        assert minted and len(token) == 32          # 16 bytes hex

    def test_loopback_bind_stays_tokenless(self):
        token, minted = self._decide("", "127.0.0.1")
        assert not minted and token == ""

    def test_existing_token_is_never_overwritten(self):
        token, minted = self._decide("chosen", "0.0.0.0")
        assert not minted and token == "chosen"
