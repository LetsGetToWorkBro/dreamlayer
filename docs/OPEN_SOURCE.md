# Open source — the decision, the shape, and the switch

DreamLayer is licensed **Apache-2.0**, whole-repo ([`LICENSE`](../LICENSE),
[`NOTICE`](../NOTICE)). This page records why, how the project is governed,
and the checklist that takes the repository public.

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

**Relicensing note (important):** while all code is written by the copyright
holder, relicensing (e.g., to AGPL, or dual-licensing a commercial edition)
is trivially possible. Once outside contributions land under DCO/Apache,
that window narrows — their code stays Apache and would need rewriting or
consent to move. If a future dual-license business is a serious option,
decide **before** merging significant external work.

## The go-public checklist

The repo is license-complete but still private. Making every public claim
true takes one pass through this list:

1. ~~**Secrets scan**~~ — done (2026-07): no keys, tokens, or credentials in
   tracked files; workflow files reference GitHub Actions secrets by name
   only; `.env.example` is a template.
2. **Decide the strategy docs' fate.** The monorepo contains business
   artifacts (`phone-app/APP_STORE.md`, store listings, `docs/CINEMA_*`
   risk/strategy notes). Two options:
   - *Publish them* — they're good reading and signal seriousness; or
   - *Keep them private* — then flipping visibility is NOT enough, because
     git history retains moved/deleted files. The clean route is a
     fresh-history public repo (single squashed initial commit) with the
     private monorepo retired or kept as archive.
   Default recommendation: publish; nothing in them is secret, only early.
3. **Configure `security@dreamlayer.app`** (Cloudflare Email Routing →
   forward to the maintainer inbox) so SECURITY.md is answerable.
4. **GitHub hygiene** — branch protection on `main` (require the pytest
   check), enable Discussions, add topics (`smart-glasses`, `ar`,
   `brilliant-labs`, `memory`, `python`), set the repo description and
   website to dreamlayer.app.
5. **DCO enforcement** — install the DCO GitHub App
   (github.com/apps/dco) so the sign-off rule in CONTRIBUTING.md is checked
   automatically on external PRs (kept out of our own CI so maintainer
   automation isn't blocked).
6. **Enroll GitHub Sponsors** (github.com/sponsors) so `.github/FUNDING.yml`
   lights up the Sponsor button; set `conduct@` and `security@` aliases in
   Cloudflare Email Routing.
7. **Keep 3–5 `good first issue`s open at all times** — they are the front
   door for new contributors; the plugin-submission and lens-idea templates
   feed the pipeline.
8. **Flip visibility** — Settings → Danger Zone → Change visibility →
   Public.
9. **Verify the claims** — the landing page's "open source — Apache-2.0"
   line, the panel's "code you can read", and the FAQ all become literally
   true the moment step 8 completes. Check the LICENSE renders on the repo
   front page.

## What stays outside the license

- The **trademarks** (NOTICE).
- **dreamlayer.app infrastructure** — the deployed site, registry instance,
  and any future DreamLayer Cloud are services, not code artifacts; running
  your own from this source is welcome, under your own name.
