"""reality_compiler — Plain English → validated Lua behaviors for Halo.

(Migrated from memoscape.reality_compiler)

    from dreamlayer.reality_compiler import RealityCompiler

    rc = RealityCompiler()
    result = rc.compile("Make me a 3-minute round timer")
    if result.success:
        halo_bridge.deploy(result.lua_code)
"""
# Re-export everything from the existing implementation
from ..memoscape_compat.reality_compiler import *  # noqa: F401,F403
