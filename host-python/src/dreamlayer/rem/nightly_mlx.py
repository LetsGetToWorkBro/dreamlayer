"""rem/nightly_mlx.py — the overnight LoRA fine-tune, on Apple silicon via MLX.

`rem/nightly.py` (NightWatch) is untouched: it does the durable-bias
consolidation each night. This is the separate, heavier step — distil what the
wearer has said into a tiny local LoRA adapter so the on-device model speaks a
little more in their world.

THIS IS THE ONE THING HERE THAT OUTLIVES A DELETION
---------------------------------------------------
Everything else the Brain does with a memory is transient — a card, a frame, a
query. Retention sweeps delete rows and they are gone. **An adapter is the
wearer's memories baked into weights, and nothing un-trains a LoRA.** So the
corpus is built to a stricter rule than any other read path in this tree, and
the manifest exists so a deletion has somewhere to land:

  * ONLY THE WEARER'S OWN WORDS. A row carrying `said_by` is somebody else
    speaking — a bystander, a colleague, whoever was in the room. Their
    sentences are in the wearer's memory because the wearer was there; that is
    not consent to train a model on them, and there is no mechanism by which
    they could withdraw it. Excluded, unconditionally.
  * ONLY KINDS THAT ARE LANGUAGE. `person`/`place`/`object` rows are index
    entries ("Person: Marcus"), not the wearer's voice, and a model trained on
    them learns to emit catalogue lines.
  * A MANIFEST, always. `adapter.json` beside the weights records exactly which
    row ids produced them. Deletion semantics for a trained adapter can only
    honestly be RETRAIN-ON-FORGET — delete the row, the adapter is stale, the
    next run rebuilds without it — and that needs to know what went in.

TRAINING RUNS AS A SUBPROCESS, DELIBERATELY
-------------------------------------------
`python -m mlx_lm.lora` rather than importing the trainer. Three reasons, in
order of how much they matter:

  1. It cannot take the Brain down. A fine-tune is a long, memory-hungry job in
     a process that also serves the wearer's panel and phone; an OOM or a hard
     crash in-process is an outage, and out-of-process it is a bad exit code.
  2. It can be STOPPED. The Veil is "one gesture, everything stops", and a
     subprocess can be killed mid-run. An in-process training loop could not be
     interrupted between steps without the trainer cooperating.
  3. mlx-lm's CLI has been stable across versions while its Python entry points
     have moved. Pinning to `--model/--train/--data/--adapter-path` is the
     surface least likely to break under a `pip install -U`.

The exact argv is logged before it runs, so a first run on a real Mac is
diagnosable rather than mysterious.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

log = logging.getLogger("dreamlayer.nightly_mlx")

try:
    import mlx.core as _mx  # type: ignore  # noqa: F401
    _HAS_MLX = True
except ImportError:
    _HAS_MLX = False

#: Memory kinds that are the wearer SPEAKING. `person`/`place`/`object` are
#: index entries ("Person: Marcus"), not language — a model trained on them
#: learns to emit catalogue lines rather than to sound like anybody.
TRAINABLE_KINDS = frozenset({"conversation", "promise", "task", "taught",
                             "memory", "note", "heard"})

#: Below this, a fine-tune learns noise. mlx-lm's own LoRA examples use
#: thousands of samples; a few dozen lines produces an adapter that is worse
#: than the base model and takes an hour to find that out.
MIN_EXAMPLES = 200

#: Held out for validation. mlx-lm requires a `valid.jsonl` and refuses to
#: start without one.
VALID_FRACTION = 0.1

#: Training iterations. mlx-lm's default is 1000; this is deliberately lower —
#: the corpus is small and personal, and an overnight job that finishes is worth
#: more than one still running at breakfast.
DEFAULT_ITERS = 300

#: Wall-clock ceiling. A run that has not converged by dawn is a run that ate
#: the machine, and the wearer wakes to a hot laptop and no adapter either way.
DEFAULT_TIMEOUT_S = 4 * 3600.0

#: Matches `ai_brain/mlx_backend.DEFAULT_MODEL`. Duplicated rather than
#: imported: `rem/` must stay loadable without the server package, and a
#: test pins the two together so the copy cannot drift.
DEFAULT_MODEL = "mlx-community/Llama-3.2-3B-Instruct-4bit"

ADAPTER_MANIFEST = "adapter.json"


@dataclass
class TrainSummary:
    trained: bool
    reason: str = ""
    examples: int = 0
    adapter_path: Optional[str] = None
    #: Memory row ids that produced this adapter. The deletion story: a row that
    #: goes away makes every adapter listing it stale.
    row_ids: list = field(default_factory=list)


class MlxNightlyTrainer:
    available = _HAS_MLX

    def __init__(self, adapter_dir: Optional[str] = None, model: str = "",
                 runner=None, now_fn=time.time):
        self.adapter_dir = adapter_dir
        self.model = model
        #: Injected in tests: (argv, timeout) -> (returncode, tail). The real
        #: one runs mlx-lm out of process.
        self._run = runner or _run_subprocess
        self._now = now_fn

    # ------------------------------------------------------------------ corpus

    def _rows(self, ring, privacy=None) -> List[dict]:
        """The rows that may lawfully be baked into weights.

        Stricter than every other read path in the tree, because this is the
        only one whose output survives the row being deleted.
        """
        if privacy is not None and hasattr(privacy, "allow_capture") \
                and not privacy.allow_capture():
            return []
        mem = getattr(ring, "memories", None)
        try:
            items = mem() if callable(mem) else (mem or [])
        except Exception:                            # noqa: BLE001
            return []
        out = []
        for it in items:
            row = it if isinstance(it, dict) else _as_row(it)
            if not row:
                continue
            summary = str(row.get("summary") or "").strip()
            if not summary:
                continue
            kind = str(row.get("kind") or "").strip().lower()
            # An UNLABELLED row is kept: the ring hands out rows with no `kind`
            # and they are the wearer's own statements. A row that NAMES a kind
            # must name a trainable one — the filter is on what is claimed, so
            # an unfamiliar kind is excluded rather than silently trained on.
            if kind and kind not in TRAINABLE_KINDS:
                continue
            if _said_by_someone_else(row):
                continue
            out.append(row)
        return out

    def _collect(self, ring, privacy=None) -> List[str]:
        """The training lines. Kept as the original name and shape — the
        capability's own tests spy on it, and a caller that wants ids uses
        `_rows`."""
        return [str(r.get("summary") or "").strip()
                for r in self._rows(ring, privacy)]

    # ----------------------------------------------------------------- writing

    def _write_data(self, root: Path, lines: List[str]) -> int:
        """mlx-lm's `--data` directory: `train.jsonl` + `valid.jsonl`.

        One `{"text": …}` per line, which is mlx-lm's plain-completions format
        and the right one here: there is no prompt/response pair in a memory,
        just the wearer's own phrasing to lean the model toward.
        """
        root.mkdir(parents=True, exist_ok=True)
        cut = max(1, int(len(lines) * VALID_FRACTION))
        valid, train = lines[:cut], lines[cut:]
        for name, rows in (("train.jsonl", train), ("valid.jsonl", valid)):
            with open(root / name, "w", encoding="utf-8") as fh:
                for line in rows:
                    fh.write(json.dumps({"text": line}, ensure_ascii=False) + "\n")
        return len(train)

    def _write_manifest(self, adapter: Path, rows: List[dict], model: str) -> None:
        """What went into these weights, so a deletion has somewhere to land.

        Written after a successful run, beside the adapter. Never contains the
        TEXT — only ids, a count and the model — because a manifest full of the
        wearer's sentences would be a second copy of the corpus sitting next to
        the first, outside every retention sweep.
        """
        try:
            (adapter / ADAPTER_MANIFEST).write_text(json.dumps({
                "model": model,
                "rows": sorted(_row_ids(rows)),
                "examples": len(rows),
                "trained_at": float(self._now()),
            }, indent=2), encoding="utf-8")
        except OSError as exc:
            log.warning("[nightly_mlx] manifest not written: %s", exc)

    # ---------------------------------------------------------------- training

    def train_nightly(self, ring, privacy=None, max_examples: int = 512,
                      iters: int = DEFAULT_ITERS,
                      timeout_s: float = DEFAULT_TIMEOUT_S) -> TrainSummary:
        """Fine-tune a LoRA adapter from what the wearer has said.

        Never raises into the dream cycle. Every refusal is a structured summary
        with the reason in it, because "nothing happened" and "it refused for a
        good reason" are the two things this product keeps confusing.
        """
        if not _HAS_MLX:
            return TrainSummary(trained=False, reason="mlx unavailable")
        model = (self.model or DEFAULT_MODEL).strip()
        if not model:
            return TrainSummary(trained=False, reason="no model configured")
        rows = self._rows(ring, privacy)[:max_examples]
        lines = [str(r.get("summary") or "").strip() for r in rows]
        if not lines:
            return TrainSummary(trained=False, reason="no capturable examples",
                                examples=0)
        if len(lines) < MIN_EXAMPLES:
            # Refusing is the useful answer. A fine-tune on forty lines makes
            # the model worse and costs an hour to discover that; saying so
            # tells the wearer their Brain needs more time, not that it broke.
            return TrainSummary(
                trained=False,
                reason=f"too few examples ({len(lines)} < {MIN_EXAMPLES})",
                examples=len(lines))
        adapter = Path(self.adapter_dir or _default_adapter_dir())
        data = adapter / "data"
        try:
            n_train = self._write_data(data, lines)
        except OSError as exc:
            return TrainSummary(trained=False,
                                reason=f"corpus write failed: {exc}",
                                examples=len(lines))
        argv = [sys.executable, "-m", "mlx_lm.lora",
                "--model", model,
                "--train",
                "--data", str(data),
                "--adapter-path", str(adapter),
                "--iters", str(int(iters)),
                "--batch-size", "1"]
        # The exact argv, so a first run on a real Mac is diagnosable rather
        # than mysterious. Safe to log: a model name, paths under the Brain's
        # own directory, and two integers — no memory text.
        log.info("[nightly_mlx] %s", " ".join(argv))
        try:
            code, tail = self._run(argv, timeout_s)
        except Exception as exc:                     # noqa: BLE001
            log.warning("[nightly_mlx] train failed: %s", type(exc).__name__)
            return TrainSummary(trained=False, reason=f"error: {exc}",
                                examples=len(lines))
        if code != 0:
            return TrainSummary(trained=False,
                                reason=f"mlx-lm exited {code}: {tail}"[:300],
                                examples=len(lines))
        if not _adapter_written(adapter):
            # A zero exit with no weights on disk is the failure this product
            # keeps meeting in other clothes: the run "succeeded" and produced
            # nothing. Never report that as trained.
            return TrainSummary(trained=False,
                                reason="mlx-lm exited 0 but wrote no adapter",
                                examples=len(lines))
        self._write_manifest(adapter, rows, model)
        log.info("[nightly_mlx] adapter written from %d examples", n_train)
        return TrainSummary(trained=True, reason="", examples=len(lines),
                            adapter_path=str(adapter), row_ids=_row_ids(rows))


# --------------------------------------------------------------------- helpers

def _default_adapter_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".dreamlayer", "adapter")


def _as_row(it) -> dict:
    summary = getattr(it, "summary", None)
    if not summary:
        return {}
    return {"summary": summary, "kind": getattr(it, "kind", ""),
            "id": getattr(it, "id", None), "meta": getattr(it, "meta", None)}


def _said_by_someone_else(row) -> bool:
    """Whether this row is another person speaking.

    `said_by` is set by the capture path when it knows who uttered a line, and
    is empty for the wearer's own. Read from the row AND from its `meta`,
    because the ring keeps it in meta while the memory store carries a JSON
    blob — the same field in two shapes, and reading only one would let half
    the corpus through unfiltered.
    """
    if _is_other(row.get("said_by")):
        return True
    meta = row.get("meta")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except ValueError:
            meta = None
    return isinstance(meta, dict) and _is_other(meta.get("said_by"))


def _is_other(value) -> bool:
    got = str(value or "").strip().lower()
    return bool(got) and got not in ("me", "self", "wearer")


def _row_ids(rows) -> list:
    out = []
    for r in rows:
        rid = r.get("id")
        if rid is not None:
            try:
                out.append(int(rid))
            except (TypeError, ValueError):
                continue
    return out


def _adapter_written(adapter: Path) -> bool:
    """Whether mlx-lm actually left weights behind."""
    try:
        return any(adapter.glob("*.safetensors"))
    except OSError:
        return False


def _run_subprocess(argv, timeout_s: float):
    """Run mlx-lm out of process. Returns (returncode, last output lines).

    `capture_output` rather than streaming: a fine-tune's stdout is a progress
    log and the only part anybody needs on failure is the tail. Bounded so a
    runaway trainer cannot fill memory with its own logging.
    """
    try:
        p = subprocess.run(argv, capture_output=True, text=True,
                           timeout=timeout_s, check=False)
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {int(timeout_s)}s"
    tail = "\n".join(((p.stderr or p.stdout or "").strip().splitlines())[-5:])
    return p.returncode, tail
