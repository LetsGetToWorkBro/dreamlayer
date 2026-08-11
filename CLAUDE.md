# Working in this repository

Notes for whoever picks this up next, human or agent. Not style rules — these
are the specific ways work in *this* codebase has gone wrong, each with the
instance that produced it. `CONTRIBUTING.md` has the ground rules; this is
about how to avoid burning a day.

Two families cover almost everything below: **a check that examined nothing
still reports success**, and **importable is not the same as reachable**.

---

## 1. A green check may have measured the empty set

The most expensive failure here, by a distance. A check passes, you believe the
property holds, and in fact the check looked at nothing at all. Every one of
these was green:

| what was checked | why it was empty |
|---|---|
| `SERVER.glob("*.py")` in a structural test | the path resolved wrong; `glob` on a missing directory yields nothing and the loop asserts over `[]` |
| a `<script>` extractor over `live.py` | the tag is spelled `<script__NONCE__>` until render time, so it found zero bodies — and `node --check` on an empty string exits 0 |
| `src.count("loadConsent()") >= 2` | the definition line `async function loadConsent(){` contains the substring, so deleting the real call still left two hits |
| `git diff … -- host-python/src/...` | run from `host-python/` with a repo-root-relative pathspec: matched no files, printed nothing, read exactly like "clean" |
| a mutation test | the `sed` anchor never matched (`IntroHost`, not `IntroLive`), so the "surviving" mutation was measured against unmutated code |
| `luacheck .` in CI | `.luacheckrc`'s `exclude_files` decides what it reads. Widen it and you get `0 warnings / 0 errors in 0 files` and **exit 0** — a green lint gate over nothing |
| `"config-file: …" in workflow_yaml` | a guard against "a config nothing loads", which passed with the line **commented out** — `#` leaves the substring exactly where it was |
| a Semgrep rule fixture | it pinned four hand-picked leaks against a 30-entry regex. Dropping `reply` from the pattern changed nothing: that case interpolated `juno_text`, still caught by the `_text$` key. It named one thing and proved another |
| `body.count("confirm(") >= 3` | there are five, so two destructive actions could lose their guard and it still passed — and it could not say which |
| 52 skipped tests | every one an `importorskip`. Legitimate locally, but CI installed none of those extras either, so the memory spine's tests ran in **no environment at all** |
| `assert w.start() is False` | asserted the no-dependency fallback with nothing gating it on the dependency being absent. With watchdog installed it passed anyway — on `OSError` errno 28, the OS out of inotify watches |
| `os_sandbox._works()` | the functional probe binds `--ro-bind / /` wholesale; the shipped `wrapper()` binds a curated list. `available()` reported a working sandbox that could not launch anything — **the probe tested a different command than the one that ships** |
| `test_os_sandbox.py` | asserts `--unshare-net` reached the argv. Make it the *value* of `--setenv` and the flag is present, the namespace is never created, and all five tests stay green — construction is not enforcement |
| the wasm capability proof | four files opening `importorskip("wasmtime")`, declared only in an extra nothing installs. 105 tests, including the one refusal that makes the plugin sandbox a boundary, ran nowhere |

**The habit:** before trusting a pass, ask *what did this actually look at?*
and make the test say so. `test_served_js_parses.py` pins this explicitly —
`test_the_scan_is_not_vacuous` asserts the extractor found something, and it
earned its place immediately: breaking the extractor fails all four vacuity
checks **while every parse check still passes**.

The same shape appears in production code, not only tests. Three CI gates read
`uv.lock`; `piper-tts` had never been *in* the lock, so all three ran clean on
an input that did not contain the problem — a GPL-3.0 dependency sat in a
shipped extra for weeks. See `decisions/`.

**Two corollaries worth stating separately, because they do not look like
tests:**

*A skip is a pass that examined nothing.* Ask where each `importorskip` runs,
not just whether skipping is reasonable here. The answer for five small wheels
was "nowhere" — `pytest.yml` already carried that argument for `networkx` and
nobody had asked it of the rest.

*A probe is not the thing it probes.* `os_sandbox._works()` and `wrapper()`
build different commands, so the probe passed on every host where the product
could not start a single plugin. Ask what the check RUNS, not what it is named
after — and where a probe exists to predict a real invocation, make it run the
real one.

*A scanner with no findings and a scanner that stopped working produce the same
output.* Six Semgrep rules, `luacheck`, and CodeQL's `paths-ignore` all report
success over an empty set. Each now has something asserting it still looks at
something: `semgrep --test` against a fixture, a file-count floor, and a pinned
ignore list.

## 2. Mutation testing has three preconditions

The discipline is worth it — it has caught real holes in tests here — but it
produces confident nonsense when done loosely.

1. **Commit first.** A `git checkout --` to undo a mutation will happily
   destroy uncommitted work. That happened: a whole rewrite was lost, and the
   mutation that then "survived" was being measured against the reverted file.
2. **Verify the mutation applied.** Print a `grep -c` before running the test.
   Two mutations "survived" here purely because the pattern never matched.
3. **Restore from the repository root.** `git checkout -- host-python/x.py`
   from inside `host-python/` fails with *pathspec did not match*, and if you
   are not reading the output you carry the mutation into the next step.
4. **Verify the mutation's EFFECT, not its text.** `SINKS = {} or {...}`
   evaluates to the original dict: the file changed and the program did not.
   Assert the thing you meant to break is broken (`len(SINKS) == 0`).

**Do it to the test you just wrote, not only to old code.** Every guard added
in the CLAUDE.md-#1 sweep was mutated immediately, and three failed:

- a Semgrep fixture that covered 4 of a 30-entry regex,
- a `config-file` check that a `#` satisfied,
- a duplicate assertion — renaming an extra failed *two* tests, one more than
  it should have, which is how the accidental copy was found.

None of the three would have been visible from reading the test. A guard that
has not been mutated is a guard nobody has checked.

## 3. Read the error before fixing it

A CodeQL failure took four rounds because the first three were plausible
guesses: the `innerHTML` sink, a reflected parameter, a duplicated hard-coded
token. Each had a story that fit "1 high severity in changed code". Each was
wrong. The annotation named a file, a line and a query
(`py/bad-tag-filter`) — and none of the three guesses was even in the right
file.

If the alert body is not visible from the tooling you have, **ask for it**.
One round of asking beats three of guessing, and guesses land real changes for
false reasons.

**You can usually fetch it yourself.** The check-run summary gives only a count
("2 new alerts including 2 high severity"), but the annotations carry the file,
line and rule:

```
curl -sS -H "Authorization: Bearer $GITHUB_TOKEN" \
  https://api.github.com/repos/<owner>/<repo>/check-runs/<id>/annotations
```

That is how the second CodeQL failure here was diagnosed in one step —
`py/request-without-cert-validation` at two exact lines. The
`/code-scanning/alerts` endpoint returns *Resource not accessible by
integration* for the CI token; the check-run annotations endpoint works.

## 4. Run the whole thing, not the part you touched

- CI type-checks **all** of `src/dreamlayer`. Checking only edited files misses
  errors in tests, which are checked too.
- Run the full suite before pushing. `type(brain).incognito_now = ...` in one
  test patched the `Brain` **class** for the rest of the session and broke five
  tests in two unrelated files — every one of which passed in isolation, so it
  read as somebody else's regression. Use `monkeypatch`.
- CI has no `paths-ignore` for CodeQL, so **tests are scanned too**. A
  hard-coded `token="..."` in a test file is a real high-severity alert.

## 5. Ask who *constructs* the consumer

The project's own recurring defect, found a dozen times: a complete, tested
seam wired to a consumer the shipped product never builds — almost always the
`Orchestrator`, which `decisions/0001` records the Brain never instantiates.

**Importable ≠ constructed ≠ called ≠ reachable from a surface.**

`scripts/capability_dependency.py` answers the first. It is not the last. A
capability whose only caller is Orchestrator-side is reachable from tests and
the simulator and from nothing a wearer runs. The fix is to re-host the plain
half Brain-side (`retention_live.py`, `attention_live.py`, `nlp_live.py` are
the worked examples), never to resurrect the Orchestrator.

The same question applies to surfaces: `/dreamlayer/status` carried a consent
report that no page drew, so a shipped feature (`mesh`) could only be granted
from a Python REPL.

## 6. Assert through the seam, not around it

A test that stubs the thing it is testing proves the stub works.

- Spy on the **effect**, not the return value. `TestNothingWritesWhileVeiled`
  drives the real methods against a veiled Brain and watches the persistence
  call, because a mis-gated method still returns something plausible.
- Prefer behaviour to source scanning. Where a source tripwire is the right
  tool — "nobody adds a second one of these" — say so in the docstring and
  keep the behavioural test alongside it.
- Two tests that only mean something together should say so. A gate that never
  opens is not a gate, it is a broken feature; assert both directions.

## 7. Prose is not enforcement

Twelve hand-written copies of the Veil gate each carried a docstring promising
it "mirrors" the others. It was true of one predicate and false of the other,
and nothing in the suite could tell. A comment saying "keep these in sync" is a
comment; `test_lockfile.py::DECIDED_BOUNDS` and
`test_veil_gate.py::TestItCannotQuietlyBecomeTwelveAgain` are the shape that
works — a table of the things that are a written-down decision, asserted, with
the reason in the failure message.

Bots cannot read prose at all. A dependency bound capped on a **licence**
boundary was proposed for widening four hours after it landed, with all
fourteen checks green.

## 8. Conventions that are not obvious

- **DCO**: `git commit -s`. CI enforces it.
- **`decisions/`**: read it before re-raising a finding. It exists so an hour
  of proving something unreachable is spent once.
- **Optional dependencies never return less than their own fallback.** An
  adapter that degrades below the no-dependency path is a regression, not a
  partial win.
- **Promotion is proof-based.** `DL_WIRED_<KEY>` is set after a seam
  demonstrably worked, never because a wheel is importable.
- **The Veil fails closed on capture and is open on recall** — see
  `decisions/0009`, and note the two writes that had been mis-filed under
  recall. If you gate something new, ask which of the two questions it is.
