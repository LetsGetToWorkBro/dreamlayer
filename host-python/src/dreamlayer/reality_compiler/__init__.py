"""reality_compiler — behaviors for Halo, authored by the user.

v1 (re-exported below): plain English → 15 hand-coded Lua templates.
v2 (``dreamlayer.reality_compiler.v2``): the Rehearsal paradigm — perform a
behavior once in sketch time, the choreographer infers a Figment (a total,
statically-budgeted scene-machine), and a fixed on-device stage runs it.

    from dreamlayer.reality_compiler.v2 import RealityCompilerV2

    rc = RealityCompilerV2()
    session = rc.rehearse()
    session.double_tap()
    session.say("rolling - three minutes")
    session.say("last ten seconds, pulse")
    session.say("then it starts again")
    result = session.finish()
    if result.ok:
        rc.keep(result.figment)
        rc.deploy(result.figment.id)
"""
# Re-export the v1 implementation for backward compatibility
from memoscape.reality_compiler import *  # noqa: F401,F403  # TODO(rename): dreamlayer.reality_compiler after rename PR lands
