# Open source — the decision, the shape, and the switch

DreamLayer is licensed **Apache-2.0**, whole-repo ([`LICENSE`](../LICENSE),
[`NOTICE`](../NOTICE)). This page records why, how the project is governed,
and where the go-public checklist stands — the repository went **public in
July 2026**, and the first external contributions have already landed.

## Why Apache-2.0, whole repo

- **Apache over MIT** — the explicit patent grant and retaliation clause
  matter for an AR/vision product; adoption-wise they're equivalent, and
  Apache is App-Store-compatible.
- **Apache over AGPL** — the audience is indie developers and wearers, and
  the project's real moat is velocity, design, and the plugin ecosystem —
  not code secrecy. The accepted trade-off: someone *could* build a closed
  fork or hosted service on this code. The copyright holder retains the
  right to offer DreamLayer Cloud commercially regardless.
- **Whole repo over open-core** — in this codebase the lenses *are* the
  engine; there is no clean runtime/premium boundary to carve without a
  re-architecture, and a mirrored "core" repo is a permanent sync tax.
  One repo, one license, no drift.

**Trademark ≠ copyright:** the code is free; the *name* is not. "DreamLayer",
the ring mark, and dreamlayer.app identity are reserved (see NOTICE). Forks
must rename. This is the standard, honest way an open project keeps
counterfeits from posing as the original.

## Governance

- **Maintainer-led (BDFL-style)** for now: the founding maintainer makes
  final product and API calls. If a core team forms, this section grows a
  real decision process.
- **Big changes start as issues**, not PRs — agree on design first.
- **The privacy contract is not up for vote**: capture guards, the Veil,
  no stranger identification. PRs weakening them are declined.

## Contributions: DCO, not CLA

Contributors sign commits (`git commit -s`) under the
[Developer Certificate of Origin](https://developercertificate.org) —
inbound = outbound Apache-2.0. A CLA was considered and rejected: it adds
signup friction and asymmetric rights for little benefit at this stage.

**Relicensing: decided, closed.** DreamLayer's business is services, not
code (DreamLayer Cloud sells hosting, inference, sync, and relay —
docs/CLOUD.md); a dual-licensed "commercial edition" has no place in that
model, and the option's mere existence chills serious contributors. So the
commitment is explicit: **this project will not relicense away from
Apache-2.0, and will not adopt a CLA to preserve that option.** Outside
contributions under DCO/Apache close the door structurally — by design,
not by accident. (Historical context: relicensing was trivially possible
while every line was the copyright holder's; the trade was considered and
declined before significant external work landed.)

## The go-public checklist — where it stands

The switch was flipped in July 2026. What each item became:

1. ~~**Secrets scan**~~ — done (2026-07): no keys, tokens, or credentials in
   tracked files; workflow files reference GitHub Actions secrets by name
   only; `.env.example` is a template.
2. ~~**Decide the strategy docs' fate**~~ — decided by doing: the repo went
   public **full-history, strategy docs included** (`phone-app/APP_STORE.md`,
   store listings, `docs/CINEMA_*`). Nothing in them was secret, only early —
   the "publish" recommendation is what happened.
3. **Configure `security@dreamlayer.app`** (Cloudflare Email Routing →
   forward to the maintainer inbox) so SECURITY.md is answerable. *Owner
   action — not verifiable from the repo; confirm and strike.*
4. **GitHub hygiene** — partial. Description is set and **Discussions is
   enabled** (2026-07-13, verified via the API); still open: branch
   protection on `main` (require the pytest check), topics (`smart-glasses`,
   `ar`, `brilliant-labs`, `memory`, `python`), and the website field
   (dreamlayer.app).
5. ~~**DCO enforcement**~~ — done, differently than planned: instead of the
   DCO GitHub App, the in-repo workflow
   [`.github/workflows/dco.yml`](../.github/workflows/dco.yml) checks every
   PR commit for a `Signed-off-by:` trailer. It runs only on
   `pull_request`, so maintainer automation pushing to branches isn't
   blocked — same exemption the App plan wanted. The App remains an
   optional add-on for its reviewer-facing UX.
6. **Enroll GitHub Sponsors** (github.com/sponsors) so `.github/FUNDING.yml`
   lights up the Sponsor button; set `conduct@` and `security@` aliases in
   Cloudflare Email Routing. *Owner action — unverified.*
7. ~~**Keep 3–5 `good first issue`s open at all times**~~ — live and
   working: five scoped issues (#199 Open Library lens, #201 simulator
   scenario, #280 watchdog, #281 zeroconf, #282 ChromaStore real-path
   tests) plus the evergreen umbrella (#200). The first external PR is
   merged (#210) and another is in review (#236). Keep restocking as they
   close.
8. ~~**Flip visibility**~~ — done: the repo is public, forked, and
   receiving outside PRs.
9. ~~**Verify the claims**~~ — the landing page's "open source —
   Apache-2.0" line, the panel's "code you can read", and the FAQ are now
   literally true; GitHub detects and renders the Apache-2.0 LICENSE on the
   repo front page.

Still open from the list: items 3, 6, and the remainder of 4 — all
owner-console actions, none of them blocking contributors today.

## What stays outside the license

- The **trademarks** (NOTICE).
- **dreamlayer.app infrastructure** — the deployed site, registry instance,
  and any future DreamLayer Cloud are services, not code artifacts; running
  your own from this source is welcome, under your own name.
