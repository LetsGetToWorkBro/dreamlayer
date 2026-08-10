---
id: 0012
title: birdnetlib's watchdog==2.1.9 is load-bearing, not incidental — relaxing the version alone ships a TypeError
status: confirmed-deferred
date: 2026-08-10
area: host-python/pyproject.toml [tool.uv] conflicts, plugins/bird_lens
---

## Claim

Issue #612 records the cost of declaring `birds` and `infra` conflicting extras:
five capabilities become mutually exclusive with `bird_song` for a reason no
wearer would recognise. Its option 1 — the one the issue says it would most like
— reads:

> `watchdog==2.1.9` is almost certainly incidental — birdnetlib uses watchdog for
> directory-watching analysis, and the API it needs is stable across 2.x→6.x. A
> PR to joeweiss/birdnetlib relaxing it to a range would fix this for everyone.

That premise is wrong, and this entry records why so that the next person does
not open a one-line upstream PR and ship a crash.

## Verdict

Confirmed as a real constraint and deferred on upstream: the pin is load-bearing
because watchdog 5.0.0 made `PatternMatchingEventHandler.__init__` keyword-only
and birdnetlib constructs it with four positional arguments, so widening the
requirement without also fixing that call site turns an import-time constraint
into a runtime `TypeError`. The upstream PR is open
([joeweiss/birdnetlib#135](https://github.com/joeweiss/birdnetlib/pull/135)) and
must be **two** edits; the conflict declaration stays until a release ships.

## Evidence

Reported by @Nitjsefnie on #612 and verified here independently rather than
taken on trust.

**1. The signature changed to keyword-only between 4.x and 5.x.**

```
$ python -c "import inspect; from watchdog.events import PatternMatchingEventHandler as P; \
             print(inspect.signature(P.__init__))"     # watchdog 6.0.0
(self, *, patterns: 'list[str] | None' = None, ignore_patterns: 'list[str] | None' = None,
 ignore_directories: 'bool' = False, case_sensitive: 'bool' = False)

$ python -c "P(['*.mp3'], None, False, True)"          # watchdog 6.0.0
TypeError: PatternMatchingEventHandler.__init__() takes 1 positional argument but 5 were given
```

…against 4.0.2, unpacked from the wheel, where the same call is fine:

```
watchdog 4.0.2 __init__ args: self, patterns=None, ignore_patterns=None,
                              ignore_directories=False, case_sensitive=False,
```

**2. birdnetlib calls it positionally, and pins accordingly.**

```
$ unzip -p birdnetlib-0.18.1-py3-none-any.whl birdnetlib/watcher.py | grep -A3 PatternMatchingEventHandler
PatternMatchingEventHandler( patterns, ignore_patterns, ignore_directories, case_sensitive )

$ unzip -p birdnetlib-0.18.1-py3-none-any.whl '*.dist-info/METADATA' | grep -i watchdog
Requires-Dist: watchdog==2.1.9
```

So `watchdog>=2.1.9,<7` on its own resolves fine and then raises the moment
`DirectoryWatcher.watch()` runs.

## What this does not change

The conflict declaration in `[tool.uv] conflicts` stays. Deleting it needs a
birdnetlib **release**, not a merged PR, and upstream's last commit was
2026-04-28 with 13 open issues — treat the timing as unknown.

Issue #612's option 2 is separately correct and separately unhelpful: DreamLayer's
`bird_lens` touches only `Analyzer` and `Recording`, neither of which imports
`birdnetlib.watcher`, so the broken call site is one this project would never
reach. There is no way to express "install birdnetlib without its watchdog
dependency", so a correct observation about our usage yields no resolver fix.

## What would overturn this

A birdnetlib release whose metadata accepts watchdog 6:

```
$ curl -s https://pypi.org/pypi/birdnetlib/json | jq -r '.info.requires_dist[] | select(contains("watchdog"))'
```

Anything other than `watchdog==2.1.9` means the pair can come out of
`[tool.uv] conflicts`. Verify with `uv lock && uv lock --check` and
`pytest src/dreamlayer/tests/test_lockfile.py`, which asserts no shipped profile
contains a conflicting pair.

One subtlety to carry into that moment, from the upstream discussion: a `<7`
ceiling is a choice rather than a necessity. watchdog 7 switches pattern
matching from `path.match()` to `path.full_match()`, under which birdnetlib's
`["*.mp3", "*.wav"]` silently stop matching. Adding `"**/*.mp3", "**/*.wav"`
*alongside* the existing patterns works on every version from 2.1.9 through
7.0.0-dev; **swapping** them regresses on ≤6 for a bare relative path. Only the
union is safe, so read the released patterns before removing a ceiling.
