"""The ASGI seam said two things that were not true.

`capabilities.py` advertised it as an "Async FastAPI mirror of the Brain", and
the module said it "wraps the SAME request handler callable, so both servers
share one implementation of the routes". Neither held:

  1. THERE IS NO SUCH CALLABLE. The stdlib server dispatches through
     `_GET_ROUTES` / `_POST_ROUTES` — dicts of bound methods taking
     `(self, path, qs)`. Nothing in the tree exposes `handler(route, body)`, so
     a builder following the docstring would go looking for a shared dispatch,
     not find one, and have to reimplement it — while the catalogue told them
     the routes were already shared.
  2. AUTH WAS OPTIONAL BY DEFAULT. `token: Optional[str] = None` meant a
     "mirror" of a token-gated server served every route it had, to anyone who
     could reach the port, with no bearer check at all — and forgetting the
     argument looked exactly like deciding not to authenticate.

Both are now stated rather than implied, and the token is required.
"""
from __future__ import annotations

import inspect
import pathlib

from dreamlayer.ai_brain import server_fastapi


class TestTheTokenIsNotOptional:
    def test_it_is_keyword_only_and_has_no_default(self):
        """Forgetting the argument must not be spellable as a working call."""
        for fn in (server_fastapi.make_app, server_fastapi.serve):
            p = inspect.signature(fn).parameters["token"]
            assert p.kind is inspect.Parameter.KEYWORD_ONLY, fn.__name__
            assert p.default is inspect.Parameter.empty, (
                f"{fn.__name__} took a default token again — an unauthenticated "
                "surface must be typed, not forgotten")

    def test_serving_unauthenticated_is_loud(self, caplog):
        import logging
        if not server_fastapi.available:
            # The warning is emitted before any FastAPI object is built, so the
            # check below still means something without the optional dep… but
            # `make_app` returns early when it is absent, so assert on the source
            # instead of pretending to exercise it.
            src = pathlib.Path(server_fastapi.__file__).read_text(encoding="utf-8")
            assert "UNAUTHENTICATED" in src
            return
        with caplog.at_level(logging.WARNING, logger="dreamlayer.server_fastapi"):
            server_fastapi.make_app(lambda route, body: {}, token=None)
        assert any("UNAUTHENTICATED" in r.getMessage() for r in caplog.records)

    def test_the_comparison_is_constant_time(self):
        """A plain `!=` on a secret leaks its prefix to anyone who can time the
        response — the stdlib server already knows this."""
        src = pathlib.Path(server_fastapi.__file__).read_text(encoding="utf-8")
        assert "hmac.compare_digest" in src
        assert 'auth != f"Bearer' not in src


class TestItNoLongerClaimsToMirrorTheBrain:
    def test_the_module_says_what_it_is_not(self):
        src = pathlib.Path(server_fastapi.__file__).read_text(encoding="utf-8")
        assert "not a mirror of the Brain server" in src
        assert "share one implementation" not in src.split('"""', 2)[2]

    def test_the_catalogue_agrees_with_the_module(self):
        """The catalogue is what a wearer reads before installing an extra; it
        drifting from the code is how a capability becomes a promise."""
        from dreamlayer.capabilities import CAPABILITIES
        cap = next(c for c in CAPABILITIES if c.key == "asgi_server")
        assert "mirror" not in cap.title.lower()
        assert "mirror" not in cap.gain.lower()
        # …and the gain says whose routes these are. `before`/`after` are NOT
        # the place to say "changes nothing today" — the catalogue's own
        # invariant (test_pack_install_ux) requires a strict improvement, and
        # the pair scores the potential once wired, exactly like every other
        # dormant entry. Setting them equal broke that and said something the
        # numbers are not for.
        assert "you write" in cap.gain.lower() or "you supply" in cap.gain.lower()
        assert cap.before < cap.after

    def test_the_claim_it_refuted_is_still_true_of_the_tree(self):
        """If a `handler(route, body)` dispatch ever DOES appear, this file's
        reasoning is stale and should be revisited rather than left asserting a
        gap that closed."""
        server = (pathlib.Path(server_fastapi.__file__).parent
                  / "server" / "server.py").read_text(encoding="utf-8")
        assert "_GET_ROUTES" in server and "_POST_ROUTES" in server
        assert "def handler(self, route, body)" not in server
