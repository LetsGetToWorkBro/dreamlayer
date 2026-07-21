"""test_receipt_verify_vectors.py — pin the receipt's canonical wire format.

Client-side verification (the panel's canonCore() and the phone's canonicalCore())
must reproduce Python's signing canonicalization BYTE-FOR-BYTE, or a legitimate
receipt would fail to verify and cry tamper. These vectors are the contract: the
exact same strings are hard-coded in the panel's `_canonSelfTest()` and the
phone's receipt verifier. If Python's canonicalization ever changes, this test
breaks and the clients must be updated in lockstep.
"""
from __future__ import annotations

import pytest

from dreamlayer.reality_compiler.sign_crypto import _canonical, verify_detached
from dreamlayer.reality_compiler import sign_crypto


# (5-field receipt core, exact canonical string the clients must reproduce).
# Covers: plain ASCII, non-ASCII (\uXXXX), an astral emoji (surrogate pair),
# escaped quote + backslash, a whole-valued float (Python keeps the ".0" that
# JS's String() drops), and a fractional float.
VECTORS = [
    ({"seq": 0, "ts": 1658236927.5, "kind": "ask", "text": "plain ascii", "prev": ""},
     '{"kind":"ask","prev":"","seq":0,"text":"plain ascii","ts":1658236927.5}'),
    ({"seq": 1, "ts": 1658236927.123456, "kind": "look",
      "text": "café naïve résumé", "prev": "abc123"},
     '{"kind":"look","prev":"abc123","seq":1,'
     '"text":"caf\\u00e9 na\\u00efve r\\u00e9sum\\u00e9","ts":1658236927.123456}'),
    ({"seq": 2, "ts": 1700000000.0, "kind": "plugin",
      "text": "emoji \U0001F389 and quote \" and backslash \\", "prev": "deadbeef"},
     '{"kind":"plugin","prev":"deadbeef","seq":2,'
     '"text":"emoji \\ud83c\\udf89 and quote \\" and backslash \\\\","ts":1700000000.0}'),
    ({"seq": 3, "ts": 1700000000.25, "kind": "tab",
      "text": "tab\there\nnewline", "prev": "x"},
     '{"kind":"tab","prev":"x","seq":3,"text":"tab\\there\\nnewline","ts":1700000000.25}'),
    # DEL (0x7F) is NOT printable-ASCII, so ensure_ascii escapes it to  —
    # the ONE character a naive "cp < 0x80 => literal" client gets wrong, which
    # would make an honest record carrying 0x7F mis-verify as tampered. The
    # printable neighbour ~ (0x7E) must stay literal (refute 2026-07-21).
    ({"seq": 4, "ts": 1700000000.0, "kind": "look",
      "text": "note\x7f~end", "prev": "y"},
     '{"kind":"look","prev":"y","seq":4,"text":"note\\u007f~end","ts":1700000000.0}'),
]


@pytest.mark.parametrize("core,want", VECTORS)
def test_canonical_matches_client_contract(core, want):
    assert _canonical(core).decode() == want


def test_client_verify_recipe_round_trips():
    """The exact recipe a client runs: canonicalize the 5-field core, then
    Ed25519-verify the signature with only the public key. Proves the vectors
    are verifiable and that a one-byte edit is caught."""
    if not sign_crypto._HAS_CRYPTO:
        pytest.skip("Ed25519 needs the cryptography (privacy) extra")
    signer = sign_crypto.Signer(b"\x11" * 32)
    pub = signer.public_key_hex
    for core, _want in VECTORS:
        sig = signer.sign(core)                       # signs _canonical(core)
        assert verify_detached(core, sig, pub) is True
        tampered = dict(core, text=core["text"] + "!")
        assert verify_detached(tampered, sig, pub) is False


def test_head_core_canonical_vector():
    """The signed head anchor's signature covers {last_seq, head, count}. The
    panel's _canonHead() and the phone's canonicalHead() reproduce this exact
    string so they can verify the length attestation independently."""
    core = {"last_seq": 41, "head": "abc123def0", "count": 42}
    assert _canonical(core).decode() == '{"count":42,"head":"abc123def0","last_seq":41}'


def test_emoji_vector_is_the_panel_self_test():
    """The panel gates signature-checking on a self-test of THIS exact vector
    (panel.py `_canonSelfTest`). Keep them identical: if this string changes,
    update the panel + phone literals too."""
    core = {"seq": 2, "ts": 1700000000.0, "kind": "plugin",
            "text": "emoji \U0001F389 and quote \" and backslash \\", "prev": "deadbeef"}
    assert _canonical(core).decode() == (
        '{"kind":"plugin","prev":"deadbeef","seq":2,'
        '"text":"emoji \\ud83c\\udf89 and quote \\" and backslash \\\\","ts":1700000000.0}')
