"""test_train_live.py — the model learns your words, and forgets them properly.

`decisions/0008` recorded `mlx_train` as unbuilt rather than unhosted: the
trainer was never written, and `MLXBackend` loaded its model with no
`adapter_path`, so even a perfect fine-tune would have produced a file nothing
could read. Both are built now.

mlx and mlx-lm are Apple-silicon only and absent here, so the training RUN is a
fake runner and the first real execution is on a Mac (the runbook is in
`decisions/0008`). Everything that decides what may be baked into weights,
however, is pure Python and is tested for real — and that is the half that
matters, because it is the only half whose mistakes cannot be undone.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from dreamlayer.ai_brain.server.server import Brain
from dreamlayer.ai_brain.server.train_live import NightlyTrain, nightly
from dreamlayer.rem.nightly_mlx import (
    MIN_EXAMPLES, TRAINABLE_KINDS, MlxNightlyTrainer, TrainSummary)


@pytest.fixture
def brain(tmp_path):
    b = Brain(tempfile.mkdtemp())
    b.config.nightly_train_enabled = True
    b.config.mlx_adapter_dir = str(tmp_path / "adapter")
    return b


class _Veil:
    def __init__(self, allow=True):
        self.allow = allow

    def allow_capture(self):
        return self.allow


class _Ring:
    def __init__(self, rows):
        self.rows = rows

    def memories(self):
        return list(self.rows)


def _rows(n, kind="conversation", said_by=None, start=1):
    out = []
    for i in range(n):
        row = {"id": start + i, "kind": kind,
               "summary": f"the lease clears on day {i}"}
        if said_by is not None:
            row["said_by"] = said_by
        out.append(row)
    return out


class TestWhatMayBeBakedIntoWeights:
    """Stricter than every other read path in the tree, because this is the
    only one whose output survives the row being deleted."""

    def test_another_persons_words_are_never_trained_on(self):
        """Their sentences are in the wearer's memory because the wearer was
        there. That is not consent to train a model on them, and there is no
        mechanism by which they could withdraw it."""
        t = MlxNightlyTrainer()
        mine = _rows(3)
        theirs = _rows(3, said_by="Marcus", start=100)
        got = t._collect(_Ring(mine + theirs), privacy=_Veil())
        assert len(got) == 3

    @pytest.mark.parametrize("marker", ["me", "self", "wearer", "Me", "SELF"])
    def test_the_wearers_own_marker_is_not_read_as_someone_else(self, marker):
        t = MlxNightlyTrainer()
        assert len(t._collect(_Ring(_rows(2, said_by=marker)),
                              privacy=_Veil())) == 2

    def test_said_by_is_read_from_meta_too(self):
        """The ring keeps it in `meta` while the memory store carries a JSON
        blob — the same field in two shapes, and reading only one would let
        half the corpus through unfiltered."""
        t = MlxNightlyTrainer()
        rows = [{"id": 1, "kind": "conversation", "summary": "a line",
                 "meta": json.dumps({"said_by": "Marcus"})},
                {"id": 2, "kind": "conversation", "summary": "another",
                 "meta": {"said_by": "Priya"}}]
        assert t._collect(_Ring(rows), privacy=_Veil()) == []

    def test_a_malformed_meta_blob_is_not_a_crash(self):
        t = MlxNightlyTrainer()
        rows = [{"id": 1, "kind": "conversation", "summary": "a line",
                 "meta": "{not json"}]
        assert len(t._collect(_Ring(rows), privacy=_Veil())) == 1

    @pytest.mark.parametrize("kind", ["person", "place", "object", "sighting"])
    def test_index_rows_are_not_language(self, kind):
        """"Person: Marcus" is a catalogue entry, not the wearer's voice, and a
        model trained on them learns to emit catalogue lines."""
        t = MlxNightlyTrainer()
        assert t._collect(_Ring(_rows(5, kind=kind)), privacy=_Veil()) == []

    def test_an_unfamiliar_kind_is_excluded_rather_than_trained_on(self):
        t = MlxNightlyTrainer()
        assert t._collect(_Ring(_rows(5, kind="telemetry")),
                          privacy=_Veil()) == []

    def test_an_unlabelled_row_is_kept(self):
        """The ring hands out rows with no `kind`, and they are the wearer's own
        statements — the filter is on what a row CLAIMS to be."""
        t = MlxNightlyTrainer()
        rows = [{"id": 1, "summary": "the lease clears friday"}]
        assert len(t._collect(_Ring(rows), privacy=_Veil())) == 1

    def test_the_veil_collects_nothing(self):
        t = MlxNightlyTrainer()
        assert t._collect(_Ring(_rows(50)), privacy=_Veil(allow=False)) == []

    def test_every_trainable_kind_actually_survives_the_filter(self):
        t = MlxNightlyTrainer()
        for kind in TRAINABLE_KINDS:
            assert t._collect(_Ring(_rows(1, kind=kind)), privacy=_Veil()), kind


class TestItRefusesRatherThanTrainingBadly:
    def _train(self, rows, code=0, writes=True, tmp=None):
        calls = []

        def _runner(argv, timeout):
            calls.append(argv)
            if writes and code == 0:
                (Path(tmp) / "adapters.safetensors").write_bytes(b"w")
            return code, "tail"
        t = MlxNightlyTrainer(adapter_dir=str(tmp), runner=_runner,
                              now_fn=lambda: 1000.0)
        t.available = True
        import dreamlayer.rem.nightly_mlx as nm
        self._nm = nm
        return t, calls

    @pytest.fixture(autouse=True)
    def _mlx_present(self, monkeypatch):
        import dreamlayer.rem.nightly_mlx as nm
        monkeypatch.setattr(nm, "_HAS_MLX", True)

    def test_too_few_examples_refuses_with_a_reason(self, tmp_path):
        t, calls = self._train(None, tmp=tmp_path)
        s = t.train_nightly(_Ring(_rows(10)), privacy=_Veil())
        assert s.trained is False
        assert "too few" in s.reason and str(MIN_EXAMPLES) in s.reason
        assert calls == [], "it started a fine-tune on ten lines"

    def test_a_veiled_night_trains_nothing(self, tmp_path):
        t, calls = self._train(None, tmp=tmp_path)
        s = t.train_nightly(_Ring(_rows(500)), privacy=_Veil(allow=False))
        assert s.trained is False and s.examples == 0
        assert calls == []

    def test_a_nonzero_exit_is_not_a_success(self, tmp_path):
        t, calls = self._train(None, code=2, tmp=tmp_path)
        s = t.train_nightly(_Ring(_rows(500)), privacy=_Veil())
        assert s.trained is False and "exited 2" in s.reason

    def test_a_clean_exit_that_wrote_nothing_is_not_a_success(self, tmp_path):
        """The failure this product keeps meeting in other clothes: the run
        'succeeded' and produced nothing."""
        t, calls = self._train(None, writes=False, tmp=tmp_path)
        s = t.train_nightly(_Ring(_rows(500)), privacy=_Veil())
        assert s.trained is False
        assert "wrote no adapter" in s.reason

    def test_a_real_run_writes_the_corpus_and_reports_the_adapter(self,
                                                                  tmp_path):
        t, calls = self._train(None, tmp=tmp_path)
        s = t.train_nightly(_Ring(_rows(500)), privacy=_Veil())
        assert s.trained is True
        assert s.adapter_path == str(tmp_path)
        data = tmp_path / "data"
        assert (data / "train.jsonl").exists()
        assert (data / "valid.jsonl").exists(), (
            "mlx-lm refuses to start without a validation set")
        first = json.loads((data / "train.jsonl").read_text().splitlines()[0])
        assert set(first) == {"text"}

    def test_the_argv_names_the_flags_mlx_lm_actually_takes(self, tmp_path):
        t, calls = self._train(None, tmp=tmp_path)
        t.train_nightly(_Ring(_rows(500)), privacy=_Veil())
        argv = calls[0]
        assert argv[1:3] == ["-m", "mlx_lm.lora"]
        for flag in ("--model", "--train", "--data", "--adapter-path",
                     "--iters"):
            assert flag in argv, flag

    def test_the_argv_carries_no_memory_text(self, tmp_path):
        """It is logged verbatim so a first run on a Mac is diagnosable."""
        t, calls = self._train(None, tmp=tmp_path)
        t.train_nightly(_Ring(_rows(500)), privacy=_Veil())
        assert "lease" not in " ".join(calls[0])


class TestTheManifestIsTheDeletionStory:
    @pytest.fixture(autouse=True)
    def _mlx_present(self, monkeypatch):
        import dreamlayer.rem.nightly_mlx as nm
        monkeypatch.setattr(nm, "_HAS_MLX", True)

    def _trained(self, tmp_path, rows):
        def _runner(argv, timeout):
            (tmp_path / "adapters.safetensors").write_bytes(b"w")
            return 0, ""
        t = MlxNightlyTrainer(adapter_dir=str(tmp_path), runner=_runner,
                              now_fn=lambda: 1000.0)
        return t.train_nightly(_Ring(rows), privacy=_Veil())

    def test_it_records_which_rows_produced_the_weights(self, tmp_path):
        s = self._trained(tmp_path, _rows(500))
        got = json.loads((tmp_path / "adapter.json").read_text())
        assert got["rows"] == sorted(r["id"] for r in _rows(500))
        assert s.row_ids

    def test_the_manifest_never_holds_the_text(self, tmp_path):
        """A manifest full of the wearer's sentences would be a second copy of
        the corpus sitting outside every retention sweep."""
        self._trained(tmp_path, _rows(500))
        assert "lease" not in (tmp_path / "adapter.json").read_text()

    def test_a_failed_run_writes_no_manifest(self, tmp_path):
        def _runner(argv, timeout):
            return 1, "boom"
        t = MlxNightlyTrainer(adapter_dir=str(tmp_path), runner=_runner)
        t.train_nightly(_Ring(_rows(500)), privacy=_Veil())
        assert not (tmp_path / "adapter.json").exists()


class TestRetrainOnForget:
    """Nothing un-trains a LoRA. The guarantee is the one that is true: a
    deleted row makes the adapter stale, it stops being used, and the next run
    rebuilds without it."""

    def _adapter(self, brain, rows_in_manifest):
        d = Path(brain.config.mlx_adapter_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / "adapters.safetensors").write_bytes(b"weights")
        (d / "adapter.json").write_text(json.dumps(
            {"model": "m", "rows": rows_in_manifest, "examples": 3}))
        return d

    def test_an_adapter_of_rows_that_still_exist_is_not_stale(self, brain,
                                                              monkeypatch):
        self._adapter(brain, [1, 2, 3])
        n = nightly(brain)
        monkeypatch.setattr(NightlyTrain, "rows",
                            lambda self: [{"id": i} for i in (1, 2, 3, 4)])
        assert n.is_stale() is False

    def test_a_deleted_row_makes_it_stale(self, brain, monkeypatch):
        self._adapter(brain, [1, 2, 3])
        n = nightly(brain)
        monkeypatch.setattr(NightlyTrain, "rows",
                            lambda self: [{"id": i} for i in (1, 3)])
        assert n.is_stale() is True

    def test_retiring_takes_the_weights_out_of_use(self, brain, monkeypatch):
        d = self._adapter(brain, [1, 2, 3])
        n = nightly(brain)
        monkeypatch.setattr(NightlyTrain, "rows", lambda self: [{"id": 1}])
        assert n.enforce_forget() is True
        assert not list(d.glob("*.safetensors")), (
            "the stale weights are still loadable")
        assert (d / "adapters.safetensors.stale").exists(), (
            "they were deleted rather than set aside")

    def test_the_backend_stops_finding_a_retired_adapter(self, brain,
                                                         monkeypatch):
        """The two halves have to agree: `MLXBackend.adapter_path` globs
        `*.safetensors`, so retiring by rename is what actually unloads it."""
        from dreamlayer.ai_brain.mlx_backend import MLXBackend
        d = self._adapter(brain, [1, 2, 3])
        b = MLXBackend(brain.config, _generate=lambda *a: "x")
        assert b.adapter_path() == str(d)
        monkeypatch.setattr(NightlyTrain, "rows", lambda self: [{"id": 1}])
        nightly(brain).enforce_forget()
        assert b.adapter_path() is None

    def test_forgetting_a_memory_retires_the_adapter(self, brain, monkeypatch):
        """Run on the ERASE path, not only on the nightly tick — a wearer who
        just deleted something must not keep being answered from weights built
        on it until 3am."""
        self._adapter(brain, [1, 2, 3])
        purged = []

        class _DB:
            def memories(self):
                return [{"id": 2}]

        class _Retr:
            def purge_memory(self, mid):
                purged.append(mid)
        monkeypatch.setattr(Brain, "_retriever_for_purge",
                            lambda self: (_Retr(), _DB()))
        called = []
        monkeypatch.setattr(NightlyTrain, "enforce_forget",
                            lambda self: called.append(1) or True)

        assert brain.forget_memory(2)["ok"] is True
        assert purged == [2]
        assert called, "the erase path never checked the adapter"

    def test_a_forget_that_deleted_nothing_does_not_touch_the_adapter(
            self, brain, monkeypatch):
        """Idempotent double-confirms and bad ids are common; nothing was
        removed, so nothing about the weights changed."""
        d = self._adapter(brain, [1, 2, 3])
        called = []
        monkeypatch.setattr(NightlyTrain, "enforce_forget",
                            lambda self: called.append(1) or True)
        brain.forget_memory(999)
        assert called == []
        assert list(d.glob("*.safetensors"))

    def test_an_unreadable_store_is_treated_as_stale(self, brain, monkeypatch):
        """Fail-closed: the wearer gets the base model, which is a worse answer
        and not a broken promise."""
        self._adapter(brain, [1, 2, 3])
        monkeypatch.setattr(NightlyTrain, "rows", lambda self: [])
        assert nightly(brain).is_stale() is True

    def test_no_adapter_is_not_stale(self, brain):
        assert nightly(brain).is_stale() is False
        assert nightly(brain).enforce_forget() is False


class TestTheScheduler:
    def test_nothing_starts_for_a_brain_that_did_not_opt_in(self, brain):
        brain.config.nightly_train_enabled = False
        assert NightlyTrain(brain).start() is False

    def test_it_starts_when_enabled_and_stops(self, brain):
        n = NightlyTrain(brain)
        assert n.start(tick_s=3600.0) is True
        assert n.start(tick_s=3600.0) is True        # idempotent
        n.stop()

    def test_it_only_fires_in_the_dream_window(self, brain, monkeypatch):
        import time as _t
        ran = []
        n = NightlyTrain(brain, now_fn=lambda: 0.0)
        monkeypatch.setattr(NightlyTrain, "run_once",
                            lambda self: ran.append(1))
        monkeypatch.setattr(_t, "localtime",
                            lambda *a: _t.struct_time(
                                (2026, 8, 3, 14, 0, 0, 0, 215, 0)))
        assert n.tick() is False
        assert ran == []
        monkeypatch.setattr(_t, "localtime",
                            lambda *a: _t.struct_time(
                                (2026, 8, 3, 3, 0, 0, 0, 215, 0)))
        assert n.tick() is True
        assert ran == [1]

    def test_it_does_not_start_a_second_run_the_same_night(self, brain,
                                                           monkeypatch):
        import time as _t
        ran = []
        n = NightlyTrain(brain, now_fn=lambda: 0.0)
        monkeypatch.setattr(NightlyTrain, "run_once",
                            lambda self: ran.append(1))
        monkeypatch.setattr(_t, "localtime",
                            lambda *a: _t.struct_time(
                                (2026, 8, 3, 3, 0, 0, 0, 215, 0)))
        n.tick()
        n.tick()
        assert ran == [1], "a fine-tune takes hours; two would fight"

    def test_a_disabled_brain_runs_nothing_even_if_asked(self, brain):
        brain.config.nightly_train_enabled = False
        assert NightlyTrain(brain).run_once() == {"trained": False,
                                                  "reason": "not enabled"}

    def test_a_trainer_that_raises_never_costs_the_night(self, brain):
        class _Boom:
            def train_nightly(self, *a, **k):
                raise RuntimeError("out of memory")
        n = NightlyTrain(brain, trainer=_Boom())
        assert n.run_once()["trained"] is False
        assert n.driving() is False

    def test_a_saved_switch_actually_starts_it(self, brain):
        """The write-only-setting trap: nothing starts a trainer for a Brain
        that booted with it off."""
        brain.config.nightly_train_enabled = False
        assert brain.start_nightly_train() is False
        brain.apply_config({"nightly_train_enabled": True})
        assert nightly(brain).enabled() is True
        brain.stop_nightly_train()

    def test_a_fresh_adapter_makes_the_backend_reload(self, brain):
        """The backend caches its model for the session, so without this the
        wearer trains overnight and keeps getting the base model until they
        restart the Brain — a feature that works and looks broken."""
        class _OK:
            def train_nightly(self, *a, **k):
                return TrainSummary(trained=True, adapter_path="/tmp/a",
                                    examples=500, row_ids=[1])

        class _Backend:
            def __init__(self):
                self._model = object()
                self._tokenizer = object()
                self.adapter_loaded = True

            def _ensure(self):
                return True
        brain._backend = _Backend()
        NightlyTrain(brain, trainer=_OK()).run_once()
        assert brain._backend._model is None, (
            "the backend kept answering from the pre-training model")


class TestTheBackendLoadsIt:
    def test_a_configured_but_empty_adapter_dir_is_not_offered(self, brain,
                                                               tmp_path):
        """`mlx_lm.load` raises on an adapter directory holding nothing, so
        this would take the whole MLX answer tier down over an overnight job
        that has not run yet."""
        from dreamlayer.ai_brain.mlx_backend import MLXBackend
        Path(brain.config.mlx_adapter_dir).mkdir(parents=True)
        assert MLXBackend(brain.config).adapter_path() is None

    def test_no_adapter_configured_is_the_normal_state(self, brain):
        from dreamlayer.ai_brain.mlx_backend import MLXBackend
        brain.config.mlx_adapter_dir = ""
        assert MLXBackend(brain.config).adapter_path() is None

    def test_real_weights_are_offered(self, brain):
        from dreamlayer.ai_brain.mlx_backend import MLXBackend
        d = Path(brain.config.mlx_adapter_dir)
        d.mkdir(parents=True)
        (d / "adapters.safetensors").write_bytes(b"w")
        assert MLXBackend(brain.config).adapter_path() == str(d)

    def test_the_model_name_is_configurable_at_last(self, brain):
        """`MLXBackend` read `mlx_model` with a getattr default and the field
        was never declared, so the Apple-silicon tier ran on a hard-coded model
        with no way to change it from any surface the product ships."""
        from dreamlayer.ai_brain.mlx_backend import MLXBackend
        assert hasattr(brain.config, "mlx_model")
        brain.config.mlx_model = "mlx-community/Qwen2.5-3B-Instruct-4bit"
        assert MLXBackend(brain.config)._model_name == brain.config.mlx_model

    def test_the_two_default_model_names_agree(self):
        """`rem/` copies it rather than importing, so `rem/` stays loadable
        without the server package. Pinned here so the copy cannot drift."""
        from dreamlayer.ai_brain.mlx_backend import DEFAULT_MODEL as A
        from dreamlayer.rem.nightly_mlx import DEFAULT_MODEL as B
        assert A == B


class TestThePromotionFollowsAnAdapter:
    def _env(self, brain, monkeypatch) -> dict:
        import dreamlayer.capabilities as caps
        seen = {}
        real = caps.report

        def _spy(env=None, **kw):
            seen.update(env or {})
            return real(env=env, **kw)
        monkeypatch.setattr(caps, "report", _spy)
        from dreamlayer.ai_brain.server.server import _capability_payload
        _capability_payload(brain)
        return seen

    def test_a_run_that_refused_does_not_promote(self, brain, monkeypatch):
        """A nightly that refused because the corpus was too small is the guard
        working, not the capability driving."""
        monkeypatch.delenv("DL_WIRED_MLX_TRAIN", raising=False)

        class _Small:
            def train_nightly(self, *a, **k):
                return TrainSummary(trained=False, reason="too few examples")
        brain._nightly_train = NightlyTrain(brain, trainer=_Small())
        brain._nightly_train.run_once()
        assert brain._nightly_train.runs == 1
        assert "DL_WIRED_MLX_TRAIN" not in self._env(brain, monkeypatch)

    def test_a_written_adapter_promotes(self, brain, monkeypatch):
        monkeypatch.delenv("DL_WIRED_MLX_TRAIN", raising=False)

        class _OK:
            def train_nightly(self, *a, **k):
                return TrainSummary(trained=True, adapter_path="/tmp/a",
                                    examples=500)
        brain._nightly_train = NightlyTrain(brain, trainer=_OK())
        brain._nightly_train.run_once()
        assert self._env(brain, monkeypatch)["DL_WIRED_MLX_TRAIN"] == "1"

    def test_the_report_does_not_build_a_trainer_to_ask(self, brain,
                                                        monkeypatch):
        monkeypatch.delenv("DL_WIRED_MLX_TRAIN", raising=False)
        assert "DL_WIRED_MLX_TRAIN" not in self._env(brain, monkeypatch)
        assert getattr(brain, "_nightly_train", None) is None

    def test_it_is_built_once_and_held(self, brain):
        assert nightly(brain) is nightly(brain)
