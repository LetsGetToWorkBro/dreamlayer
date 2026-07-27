---
id: NNNN
title: One line, stating the conclusion rather than the topic
status: refuted | accepted-risk | confirmed-deferred | needs-recheck
date: YYYY-MM-DD
area: module/path or subsystem name
---

## Claim

What was asserted, and where it came from (issue number, audit wave, review
comment). State it in its strongest form — a straw man here is a finding that
gets re-raised next quarter.

## Verdict

One sentence. Lead with the conclusion.

## Evidence

Reproducible commands and their actual output. Not prose about having checked.

```
$ grep -rn "Something(" src/dreamlayer --include=*.py | grep -v "/tests/"
src/dreamlayer/x/y.py:68:    thing = Something(
```

If the conclusion required running code rather than reading it, say what you ran
and what it printed. Measurements beat adjectives.

## What would overturn this

The specific check that flips the verdict. Runnable, and cheap enough that
someone will actually run it.

## Consequences

What follows from the verdict: what not to do, what to watch, what a future fix
would have to touch. Omit if there is genuinely nothing.
