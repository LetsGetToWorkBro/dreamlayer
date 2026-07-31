"""Two river-backed seams that made the product WORSE when installed.

Both reported by @Nitjsefnie (#551, #553), both reproduced before fixing.

This is the mirror image of the reachability audit running through this repo.
That one asks "is the capability wired up at all?"; these two were wired, ran,
and reported `active` on the meter while behaving worse than the dependency-free
fallback they were supposed to improve on. A capability that is merely dormant
costs the wearer nothing. One that is active and wrong costs them the feature
AND the honest signal that it is broken.

  * #551 — `fading_factor` IS alpha, not its complement, so `1 - alpha` turned
    the slowest-adapting baseline into the fastest and the calibrated storm
    warning stopped firing.
  * #553 — `hash(key) % 997` as the model's only feature. Python randomises
    string `hash()` per process, so learned state meant something different on
    every run.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest


class TestTheWeatherBaselineAdaptsAtTheRateItWasAskedFor:
    """#551. Asserted against the FALLBACK rather than against a literal: the
    two paths are meant to be the same estimator, so the fallback is the
    specification and any drift between them is the bug."""

    def _fallback(self, values, alpha):
        mean = None
        for v in values:
            mean = v if mean is None else mean + alpha * (v - mean)
        return mean

    def test_the_two_paths_agree(self):
        river = pytest.importorskip("river")           # noqa: F841
        from dreamlayer.dream_mode.weather_river import RiverWeather
        alpha = 0.05
        values = [0.0] * 20 + [1.0] * 10
        w = RiverWeather(alpha)
        assert w._roll is not None, "river installed but the seam did not build"
        got = None
        for v in values:
            got = w.update(v)
        assert got == pytest.approx(self._fallback(values, alpha), abs=1e-6)

    def test_a_slow_baseline_does_not_fully_adapt(self, ):
        """The behavioural consequence, independent of the fallback. With the
        inversion, this read 1.0 — the baseline had completely followed the new
        level, so nothing could ever look like a departure from it and the storm
        warning went quiet."""
        pytest.importorskip("river")
        from dreamlayer.dream_mode.weather_river import RiverWeather
        w = RiverWeather(0.05)
        for v in [0.0] * 20 + [1.0] * 10:
            got = w.update(v)
        assert got < 0.5, f"a slow baseline fully adapted in 10 samples: {got}"

    def test_a_fast_alpha_really_is_fast(self):
        """The other direction, so the fix is not just "always slow" — alpha has
        to still mean what it says."""
        pytest.importorskip("river")
        from dreamlayer.dream_mode.weather_river import RiverWeather
        slow, fast = RiverWeather(0.05), RiverWeather(0.9)
        for v in [0.0] * 20 + [1.0] * 10:
            s = slow.update(v)
            f = fast.update(v)
        assert f > s

    def test_the_fallback_is_unchanged_by_the_fix(self):
        """The no-river path is the reference and must not have moved."""
        from dreamlayer.dream_mode.weather_river import RiverWeather
        w = RiverWeather(0.05)
        w._roll = None                                 # force the fallback
        got = None
        for v in [0.0] * 20 + [1.0] * 10:
            got = w.update(v)
        assert got == pytest.approx(self._fallback([0.0] * 20 + [1.0] * 10, 0.05),
                                    abs=1e-9)


# The only honest way to test cross-process stability is across processes: within
# one interpreter `hash()` is perfectly consistent, which is exactly why this
# survived every in-process test the repo had.
_PROBE = textwrap.dedent("""
    import sys
    sys.path.insert(0, {path!r})
    from {module} import _bucket
    print(",".join(str(_bucket(k)) for k in ("alpha", "beta", "gamma", "figment-7")))
""")


def _buckets_under_seed(module: str, seed: str) -> str:
    import pathlib
    src = str(pathlib.Path(__file__).resolve().parents[2])
    out = subprocess.run(
        [sys.executable, "-c", _PROBE.format(path=src, module=module)],
        capture_output=True, text=True,
        env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


@pytest.mark.parametrize("module", [
    "dreamlayer.orchestrator.taste_river",
    "dreamlayer.reality_compiler.v2.repertoire_ranker",
])
class TestTheModelFeatureIsStableAcrossProcesses:
    """#553. Both rankers key their single feature on the same idea, so both are
    checked — fixing one and leaving the other would leave the ranking
    nondeterministic exactly where the Vault promises it is not."""

    def test_the_bucket_does_not_move_with_the_hash_seed(self, module):
        seeds = ["0", "3", "7", "42", "random"]
        results = {s: _buckets_under_seed(module, s) for s in seeds}
        assert len(set(results.values())) == 1, results

    def test_the_bucket_is_in_range(self, module):
        mod = __import__(module, fromlist=["_bucket"])
        assert all(0 <= mod._bucket(k) < mod._BUCKETS
                   for k in ("", "a", "figment-7", "x" * 500))

    def test_different_keys_mostly_land_apart(self, module):
        """Not a distribution proof — just that it is not degenerate. A bucket
        function returning a constant would satisfy every stability test above
        while destroying the feature entirely."""
        mod = __import__(module, fromlist=["_bucket"])
        keys = [f"figment-{i}" for i in range(50)]
        assert len({mod._bucket(k) for k in keys}) > 40

    def test_it_is_not_python_hash(self, module):
        """The specific thing that was wrong. If `_bucket` ever goes back to
        `hash()`, this fails under any seed but the one that happens to match."""
        mod = __import__(module, fromlist=["_bucket"])
        assert mod._bucket("alpha") != hash("alpha") % mod._BUCKETS or \
            _buckets_under_seed(module, "0") == _buckets_under_seed(module, "42")


class TestTheRankerKeepsItsDeterminismPromise:
    """`repertoire_ranker`'s docstring promises "Deterministic, and rebuildable
    from the Vault history (`hydrate`) so it survives a restart". `hydrate`
    replayed history faithfully into buckets that no longer meant what they meant
    when the model learned them, so the promise did not hold across a restart."""

    def test_hydrate_from_the_same_history_gives_the_same_ranking(self):
        from dreamlayer.reality_compiler.v2.repertoire_ranker import RepertoireRanker
        history = {
            "alpha": [{"action": "deploy", "hour": 9}, {"action": "complete", "hour": 9}],
            "beta": [{"action": "deploy", "hour": 9}, {"action": "banish", "hour": 9}],
            "gamma": [{"action": "deploy", "hour": 9}, {"action": "complete", "hour": 9}],
        }
        a, b = RepertoireRanker(), RepertoireRanker()
        a.hydrate(history)
        b.hydrate(history)
        for fid in history:
            assert a.score(fid, 9) == pytest.approx(b.score(fid, 9))
