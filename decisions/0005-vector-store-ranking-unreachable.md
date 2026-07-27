---
id: 0005
title: "`VectorStore` ranking is unreachable — but not for the reason first given"
status: refuted
date: 2026-07-27
area: memory/vector_store
---

## Claim

Raised in the full-stack audit (wave 1): `memory/vector_store.py`'s ranking is
weak enough to return poor recall ordering, so semantic search could surface the
wrong memories.

Wave 2 refuted it, and PR #530's description recorded the refutation as: *"no
production code constructs that class, and the shipped `Retriever` is both
stronger and honest about making no ranking claim."*

## Verdict

The conclusion holds — no shipping code path reaches `VectorStore` — but **the
stated reason was wrong**, and would not survive the first person who checked
it. Two modules do construct it.

## Evidence

The one-hop claim is false. `VectorStore` is constructed twice:

```
$ grep -rn "VectorStore(" src/dreamlayer --include=*.py | grep -v "/tests/"
src/dreamlayer/memory/lance_store.py:28:        self._fallback = VectorStore(db, embedder=self.embedder)
src/dreamlayer/memory/chroma_store.py:30:        self._fallback = VectorStore(db, embedder=self.embedder)
```

The correct argument is one hop further out: **nothing constructs the wrappers.**
Outside their own defining modules, `LanceStore` and `ChromaStore` are not
referenced anywhere in the package:

```
$ grep -rn "LanceStore\|ChromaStore\|lance_store\|chroma_store" src/dreamlayer \
    --include=*.py | grep -v "/tests/" | grep -v "memory/lance_store.py\|memory/chroma_store.py"
(no output)
```

And the other route in — `Retriever.vector_store` — is a constructor parameter
(`memory/retrieval.py:65`) whose only production caller is the retention sweep
(`orchestrator/ops_dream_rem.py:74`), which never runs (see
[0001](0001-retention-lifecycle-never-runs.md)).

So the class is unreachable in a shipped build by two independent routes, and
the audit's underlying concern about ranking quality is moot for now.

## What would overturn this

```
grep -rn "LanceStore\|ChromaStore" src/dreamlayer --include=*.py | grep -v "/tests/" \
  | grep -v "memory/lance_store.py\|memory/chroma_store.py"
```

returning a hit — i.e. someone wires an alternate vector store into the
retriever. At that moment the ranking question becomes live again and this entry
must be reopened, **not** cited as prior clearance.

Note the dependency: this entry rests partly on 0001 staying true. Fixing the
retention lifecycle makes the `ops_dream_rem.py:74` route real. Re-read both
together.

## Consequences

The reusable lesson is about the refutation, not the code:

- **"Nothing constructs X" is a claim about a grep, and greps are cheap — run
  the grep.** The original wording was asserted from memory during a wave that
  was itself checking other people's memory. It was one command from being right.
- A refutation that is *directionally* correct but *specifically* wrong is worse
  than no refutation. It gets cited, it sounds authoritative, and it collapses
  the first time someone verifies it — taking the correct conclusion down with
  it.
- Unreachability arguments should state the **full chain** and name each link, so
  a reader can check any one of them. A single-sentence "nothing uses it" is not
  auditable.
