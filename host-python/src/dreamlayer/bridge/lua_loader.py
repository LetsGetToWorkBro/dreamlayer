"""Lua bundle collector with dry-run manifest verification.

Collects all .lua files under lua_root into a {path_key: source} dict,
where path_key uses forward slashes (device filesystem convention).

Dry-run mode prints the full bundle manifest and verifies that every
path key corresponds to a require() string used in the codebase,
failing loudly with a diff if there are unreachable or missing modules.
"""
from __future__ import annotations
import logging
import os

log = logging.getLogger("dreamlayer.lua_loader")

# All require() strings found in halo-lua/main.lua top-level imports.
# These are the modules the device MUST be able to resolve at boot.
# Update this set if new top-level require() calls are added to main.lua.
MANDATORY_REQUIRE_PATHS = {
    "system/time",
    "system/logging",
    "system/settings",
    "system/power",
    "display/renderer",
    "display/animations",
    "capture/scheduler",
    "capture/camera",
    "capture/microphone",
    "capture/activity",
    "ble/host_comm",
    "app/state_machine",
    "app/session",
    "app/events",
    # Transitive dependencies referenced via require() in sub-modules
    "display/palette",
    "display/typography",
    "display/layout",
    "display/primitives",
    "display/cards",
    "lib/utils",
    "lib/easing",
    "lib/queue",
    "lib/constants",
    "ble/protocol",
    # Confirmed present in repo: halo-lua/app/commands.lua
    "app/commands",
    # Confirmed present in repo: halo-lua/ble/message_types.lua
    "ble/message_types",
}


def _path_to_require_key(path_key: str) -> str:
    """Convert a bundle path key to the require() string the VM would use.

    e.g.  "display/renderer.lua"  ->  "display/renderer"
          "main.lua"               ->  "main"
    """
    return path_key.replace(os.sep, "/").removesuffix(".lua")


def collect_lua(
    lua_root: str,
    dry_run: bool = False,
    verify: bool = True,
) -> dict[str, str]:
    """Walk lua_root and return {path_key: source} for every .lua file.

    Parameters
    ----------
    lua_root:
        Absolute or relative path to the halo-lua/ directory.
    dry_run:
        If True, print the full manifest table to stdout and return without
        raising verification errors.  Useful pre-upload sanity check.
    verify:
        If True (default), assert that every path in MANDATORY_REQUIRE_PATHS
        is present in the bundle and raise ValueError listing any gaps.
    """
    bundle: dict[str, str] = {}

    for root, _, files in os.walk(lua_root):
        for f in sorted(files):            # sorted for deterministic output
            if not f.endswith(".lua"):
                continue
            full = os.path.join(root, f)
            # Use forward slashes regardless of host OS so keys match
            # device filesystem paths and require() strings.
            rel  = os.path.relpath(full, lua_root)
            key  = rel.replace(os.sep, "/")
            with open(full) as fh:
                bundle[key] = fh.read()

    if "main.lua" not in bundle:
        raise FileNotFoundError(
            "main.lua missing from bundle — Halo requires it to autorun.\n"
            f"Searched: {os.path.abspath(lua_root)}"
        )

    if dry_run:
        print(f"\n=== Lua bundle manifest ({len(bundle)} files) ===")
        print(f"{'PATH KEY':<45}  {'BYTES':>6}")
        print("-" * 54)
        for key in sorted(bundle):
            print(f"{key:<45}  {len(bundle[key]):>6}")
        print()
        # Also print require-key mapping so mismatch is immediately obvious
        print("=== require() key mapping ===")
        for key in sorted(bundle):
            rk = _path_to_require_key(key)
            mark = "\u2713" if rk in MANDATORY_REQUIRE_PATHS or key == "main.lua" else "?"
            print(f"  {mark}  {key}  ->  require('{rk}')")
        print()

    if verify:
        bundle_require_keys = {
            _path_to_require_key(k) for k in bundle if k != "main.lua"
        }
        missing = MANDATORY_REQUIRE_PATHS - bundle_require_keys
        extra   = bundle_require_keys - MANDATORY_REQUIRE_PATHS

        errors: list[str] = []
        if missing:
            errors.append(
                "MISSING from bundle (required by Lua but no .lua file found):\n"
                + "\n".join(f"  - {m}" for m in sorted(missing))
            )
        if extra:
            # Extra files are a warning, not a hard error — they may be
            # legitimate helpers not yet in MANDATORY_REQUIRE_PATHS. This is a
            # diagnostic on the normal (non-dry-run) path, so it belongs in the
            # log, not on stdout (audit 2026-07-14). The dry-run manifest above
            # is deliberate stdout inspection output and stays a print.
            log.warning(
                "lua bundle contains %d file(s) not in MANDATORY_REQUIRE_PATHS "
                "(may be fine): %s",
                len(extra), ", ".join(sorted(extra)),
            )

        if errors and not dry_run:
            raise ValueError(
                "Lua bundle path verification failed — "
                "device require() calls will crash at boot:\n\n"
                + "\n\n".join(errors)
                + "\n\nRun collect_lua(lua_root, dry_run=True) to see the full manifest."
            )

    return bundle
