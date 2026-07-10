# ADR 0001 — Plugin extension model: `register(ctx)` + capabilities, not pluggy

**Status:** Accepted · **Date:** 2026-07 · **Scope:** the DreamLayer SDK / plugin API

## Context

DreamLayer's host already ships `pluggy` (the pytest/Datasette plugin framework)
as an optional dependency and has a `hookspecs.py`. As we froze the public SDK
surface, we had to decide whether the *supported* extension model should be
pluggy hookspecs (à-la-carte hook implementations, discovered and fanned out by
pluggy) or the current `register(ctx)` + capability model (a plugin is handed a
narrow context and calls `ctx.add_*`, gated by declared capabilities).

The research that prompted this correctly notes pluggy's strengths: multi-point
à-la-carte contribution, multi-plugin fan-out, ordered/`firstresult`/wrapper
semantics.

## Decision

**Keep `register(ctx)` + capabilities as the supported model. Do not adopt
pluggy in the SDK.** Add a lightweight `contributions()` introspection helper so
the à-la-carte value pluggy advertises is *visible* without it.

## Rationale

1. **The SDK is a facade meant to be minimal.** `dreamlayer.sdk` and the CLI are
   deliberately stdlib-only so a plugin author's install (and CI) stays light and
   can't conflict on a transitive dep. Making pluggy a *required* part of the
   supported surface contradicts that; making it optional means two parallel
   mechanisms.
2. **`register(ctx)` is already à-la-carte and multi-point.** One plugin
   contributes to several extension points in a single `register` —
   `ctx.add_card_renderer(...)` *and* `ctx.add_object_provider(...)` *and*
   `ctx.subscribe(...)`. That is the exact ergonomics pluggy hook-per-point buys,
   without inheritance or discovery machinery.
3. **Multi-plugin fan-out already exists** where it belongs: every object
   provider is consulted, every glance candidate bids and the arbiter picks
   (`firstresult`-style), the Brain/Perception routers try tiers in order, and
   the `PluginEventBus` + `dispatch_event` fan an event out to all subscribers.
   We don't need pluggy's hook manager to get fan-out.
4. **Explicit capability grants beat implicit hook discovery for a
   permission-sensitive platform.** DreamLayer's whole safety story is that a
   plugin declares what it needs and the host grants/denies it, with a gate and
   a transparency log. "Discovered hook implementations get called" is the wrong
   default when the question is *"what is this untrusted code allowed to touch."*
5. **We keep the freedom to change internals.** `PluginContext` is a stable
   Protocol (`PluginContextProtocol`); the concrete registries behind it can move
   without breaking plugins — the same decoupling pluggy would give, already had.

## The concrete piece we did build

The one genuine gap pluggy would have filled is *seeing what a plugin
contributes without running it through the full smoke test*. So:

- `dreamlayer.sdk.contributions(plugin)` runs `register` against a recording
  context and returns the à-la-carte contribution map (card types by name, other
  extension points by count).
- `dreamlayer plugins info` surfaces it (`--json` for tooling), so the store, the
  panel, and a reviewer can answer "what does this plugin add?" — the
  VS-Code-`contributes` value, delivered without a manifest DSL or a new dep.

## Consequences

- Plugin authors keep the small, one-doorway API; no hook decorators to learn.
- If a future need genuinely requires ordered/wrapper hook semantics beyond the
  arbiter/router/bus we have, revisit this ADR — pluggy remains available in the
  host and this decision is reversible.
