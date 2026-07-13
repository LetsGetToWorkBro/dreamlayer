"""dreamlayer.testkit — deterministic concurrency testing for the hub.

The pragmatic Python answer to deterministic-simulation testing (the marquee
DST tools — madsim/shuttle/turmoil — are Rust-only): a virtual clock plus a
seeded, replayable interleaving harness, applied to the orchestrator's real
race surfaces. See docs/CONCURRENCY.md § Verifying it.
"""
from .dst import SimClock, Interleaver, Trace, InterleavingFailure, run_threads

__all__ = ["SimClock", "Interleaver", "Trace", "InterleavingFailure",
           "run_threads"]
