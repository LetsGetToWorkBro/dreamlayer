---
id: 0013
title: The 26-alert Dependabot wall is two real fixes, three unreachable advisories, and one fix line both upstreams cap us below
status: accepted-risk
date: 2026-08-11
area: phone-app/package-lock.json, host-python/uv.lock
---

## Claim

Every push banner says GitHub found 26 vulnerabilities on the default branch
(1 critical, 18 high, 7 moderate), and Dependabot has opened zero fix PRs for
them. Read together those two facts look like an unmonitored security backlog.

The alerts API is not readable with the CI token (`Resource not accessible by
integration`, same as `/code-scanning/alerts` — see CLAUDE.md §3), so this
entry reconstructs the wall from the lockfiles themselves and records a verdict
per item, so the banner stops being re-investigated from scratch.

## Verdict

Two advisories were fixable and are fixed (js-yaml, nanoid — phone-app
lockfile). Everything left is either unreachable from any surface this project
runs, or fixed only in versions both of our upstreams cap us below. Zero fix
PRs is Dependabot being *correct*: there is no in-range bump that clears any
remaining alert.

## Evidence

Reconstruction: every `name==version` in `uv.lock` (472 packages), every crate
in `reality-core/Cargo.lock` (zero external crates — clean), and `npm audit
--package-lock-only` in `web/` (clean) and `phone-app/` (20 findings), checked
against OSV:

```
$ python3 -c '...' # POST https://api.osv.dev/v1/querybatch, 472 PyPI queries
75 vuln hits (python)   # pillow x2 forks, chromadb, datasette, diskcache
```

Per item:

**phone-app npm (was 20, now 18, all transitive under the Expo 57 toolchain).**
`npm audit fix --package-lock-only` cleared js-yaml (CVE-2026-59870, quadratic
!!omap) and nanoid, plus in-range patch refreshes. The remaining 18 chain to
two leaves:

- `image-size 1.2.1` (metro asset pipeline): of its three DoS advisories, two
  (GHSA-5p2g-fcmc-qvqq, GHSA-w3rx-r6r6-pgpr) have **no fixed release in any
  version** — OSV `introduced: 0, fixed: []`. There is nothing to bump or
  override to. It parses the app's *own* bundled assets at build time.
- `uuid 7.0.3` (under `xcode 3.0.1`, used by expo prebuild): the advisory
  (GHSA-w5hq-g745-h8pq) is a bounds miss in v3/v5/v6 generation *when a `buf`
  argument is passed*. xcode generates v4 pbxproj IDs without `buf`; the
  vulnerable path is not called. Forcing 11.1.1 via overrides breaks xcode's
  `^7` range for a path we never execute.

npm's own "fix" for the 18 is `expo 57 → 53` and `react-native 0.86 → 0.72` —
a double-major *downgrade*. Not a fix.

**chromadb 1.5.9 — the 1 critical (GHSA-f4j7-r4q5-qw2c), unreachable.** The
vulnerability is pre-auth code injection in the ChromaDB *server's*
`/api/v2/.../collections` endpoint. This project only ever constructs embedded
clients — the endpoint does not exist in-process:

```
$ grep -rn "chromadb\." src/dreamlayer --include=*.py | grep -v tests
memory/chroma_store.py:43:  chromadb.PersistentClient(path=self._path) if self._path
memory/chroma_store.py:44:  else chromadb.EphemeralClient()
memory/chroma_store.py:162:  client = chromadb.PersistentClient(path=self._path)
```

No fixed release exists (`fixed: []`) as of this date, so there is also no
bump that would clear the alert.

**datasette 0.65.2 (PYSEC-2023-154) — scanner over-match, not our bug.** The
advisory's own text: "affects Datasette instances running a Datasette 1.0
alpha — 1.0a0, 1.0a1, 1.0a2 or 1.0a3"; fixed in 1.0a4. 0.65.2 is not in that
family, our bound `>=0.65,<1` cannot even install an alpha, and the explorer
serves immutable, `--host 127.0.0.1` (`memory/datasette_app.py:command`).

**diskcache 5.6.3 (via `outlines`) — pickle by design, local-compromise
precondition.** "An attacker with write access to the cache directory" can
plant a pickle. Write access to the app-private cache dir on the wearer's own
machine *is already* local compromise. No fixed release exists ("through
5.6.3" = every version to date).

**pillow — the real backlog, capped below its fix line by both upstreams.**
Every advisory on the locked 10.4.0 and 11.3.0 forks is fixed in
12.1.1–12.3.0. Neither fork can get there:

- ~~the `vision` fork sits at 10.4.0 because moondream 1.x requires
  `pillow<11`~~ — done: #647 moved moondream to 2.0.1 (pillow uncapped) and
  the vision fork now resolves at 11.3.0 alongside `dream`. The 10.4.0 fork
  that remains belongs to `doc-ocr` alone: surya-ocr 0.22.1 pins
  `pillow<11,>=10.2.0`;
- the `dream`/`hardware`/`vision` fork sits at 11.3.0 because brilliant-msg
  requires `pillow<12.0.0,>=11.1.0`, and its latest release (7.0.0, checked
  2026-08-11 on PyPI) still does.

The pillow surface here is the wearer's own camera frames and generated dream
imagery, not hostile documents — the font/PSD/PDF parser bugs need attacker-
crafted files. Elevated the moment any pillow path renders untrusted input.

## What would overturn this

- `python3 -c "import json,urllib.request; d=json.load(urllib.request.urlopen('https://pypi.org/pypi/brilliant-msg/json')); print(d['info']['version'], [x for x in d['info']['requires_dist'] if 'illow' in x])"`
  — a release allowing pillow 12 reopens the dream-fork bump.
- #647 landed (2026-08-11): the vision fork moved to 11.3.0 — the pillow
  section above reflects it. What remains is brilliant-msg (<12) and, for the
  doc-ocr fork, surya-ocr (<11):
  `python3 -c "import json,urllib.request; d=json.load(urllib.request.urlopen('https://pypi.org/pypi/surya-ocr/json')); print(d['info']['version'], [x for x in d['info']['requires_dist'] if 'illow' in x])"`
- A chromadb release with a non-empty `fixed:` for GHSA-f4j7-r4q5-qw2c — bump
  it even though unreachable, so the alert clears.
- Any new code path constructing `chromadb.HttpClient` or running
  `chroma run` / `datasette serve --host 0.0.0.0` flips the two "unreachable"
  verdicts to live findings.
- An Expo SDK release whose toolchain drops image-size/uuid-7 — take it and
  re-run `npm audit`.

## Consequences

- Do not "fix" the phone-app alerts with `npm audit fix --force`; the forced
  resolution is a two-major downgrade of the app's runtime.
- Do not add a `uuid` override under xcode; it trades a real build risk for an
  unreachable vuln path.
- The pillow section is the second thing (after the six `[tool.uv]` conflict
  pairs) hanging on #647 — noted there.
- Re-run the OSV reconstruction (commands above) rather than re-guessing the
  banner; it takes about a minute.
