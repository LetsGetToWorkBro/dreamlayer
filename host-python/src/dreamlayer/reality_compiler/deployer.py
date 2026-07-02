"""reality_compiler/deployer.py — Halo deployment wrapper.

Wraps the brilliant-msg startup sequence:
  break/reset/break → upload libs → upload app → start loop

Hardware is optional: if `brilliant_msg` is not installed the deployer
runs in DRY_RUN mode and logs what it would do without touching hardware.
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

try:
    from brilliant_msg import BrilliantMsg  # type: ignore
    _HW_AVAILABLE = True
except ImportError:
    _HW_AVAILABLE = False


class DeployResult:
    def __init__(self, success: bool, mode: str, message: str = "") -> None:
        self.success = success
        self.mode = mode          # "hardware" | "dry_run"
        self.message = message

    def __repr__(self) -> str:
        return f"DeployResult(success={self.success}, mode={self.mode!r})"


class HaloDeployer:
    """Deploys a Lua behavior to Halo glasses via BLE.

    If brilliant-msg is not installed, runs in dry-run mode and prints
    what would be deployed without attempting BLE connection.

    Parameters
    ----------
    dry_run : force dry-run mode even if hardware libs are present
    """

    def __init__(self, dry_run: bool = False) -> None:
        self._dry_run = dry_run or not _HW_AVAILABLE

    async def deploy(self, lua_code: str, run_sec: int = 3600) -> DeployResult:
        """Upload *lua_code* to Halo and start the app.

        Parameters
        ----------
        lua_code : generated Lua string
        run_sec  : seconds to keep the app running before stopping
        """
        if self._dry_run:
            return self._dry_run_deploy(lua_code)
        return await self._hw_deploy(lua_code, run_sec)

    def _dry_run_deploy(self, lua_code: str) -> DeployResult:
        lines = lua_code.count("\n")
        log.info("[DRY RUN] Would deploy %d lines of Lua to Halo", lines)
        log.info("[DRY RUN] Sequence: break → upload_stdlua_libs → upload_frame_app → start")
        return DeployResult(
            success=True,
            mode="dry_run",
            message=f"Dry run OK ({lines} lines of Lua)",
        )

    async def _hw_deploy(self, lua_code: str, run_sec: int) -> DeployResult:
        """Real deployment via brilliant-msg."""
        with tempfile.TemporaryDirectory() as tmp:
            lua_path = Path(tmp) / "main.lua"
            lua_path.write_text(lua_code)

            try:
                d = BrilliantMsg()  # type: ignore
                await d.connect()
                await d.upload_stdlua_libs(["data", "plain_text"])
                await d.upload_frame_app(str(lua_path))
                d.attach_print_response_handler()
                await d.start_frame_app()
                log.info("Halo app started — running for %d s", run_sec)
                await asyncio.sleep(run_sec)
                await d.stop_frame_app()
                await d.disconnect()
                return DeployResult(success=True, mode="hardware", message="Deployed OK")
            except Exception as exc:
                return DeployResult(success=False, mode="hardware", message=str(exc))
