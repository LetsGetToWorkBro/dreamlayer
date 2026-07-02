"""reality_compiler/compiler.py — End-to-end orchestrator.

parse → validate intent → codegen → emulator validate → (optional) deploy

Usage
-----
    import asyncio
    from dreamlayer.reality_compiler import RealityCompiler

    rc = RealityCompiler()
    result = await rc.compile("3 minute round timer with 20s overtime")
    print(result.lua_code)
    print(result.validation)
    # result.deploy_result is None unless deploy=True passed
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

from .intent_parser import IntentParser
from .schema import BehaviorIntent
from .codegen import CodeGenerator
from .validator import EmulatorValidator, ValidationResult
from .deployer import HaloDeployer, DeployResult
from .template_library import get as get_template


@dataclass
class CompileResult:
    intent: BehaviorIntent
    lua_code: str
    host_code: str
    validation: ValidationResult
    deploy_result: Optional[DeployResult] = None

    @property
    def ok(self) -> bool:
        return self.validation.passed

    def summary(self) -> str:
        lines = [
            f"Behavior : {self.intent.type}",
            f"Validated: {'YES' if self.validation.passed else 'NO'}",
            f"Lua lines: {self.lua_code.count(chr(10))}",
        ]
        if self.deploy_result:
            lines.append(f"Deployed : {self.deploy_result.mode} — {self.deploy_result.message}")
        if self.validation.warnings:
            for w in self.validation.warnings:
                lines.append(f"  warn: {w}")
        return "\n".join(lines)


class RealityCompiler:
    """Orchestrates: NL parse → codegen → emulator validate → optional deploy.

    Parameters
    ----------
    dry_run : If True (default) deploy is simulated, not sent to hardware.
    """

    def __init__(self, dry_run: bool = True) -> None:
        self._parser    = IntentParser()
        self._codegen   = CodeGenerator()
        self._validator = EmulatorValidator()
        self._deployer  = HaloDeployer(dry_run=dry_run)

    async def compile(
        self,
        text: str,
        deploy: bool = False,
        run_sec: int = 3600,
    ) -> CompileResult:
        """Parse *text*, generate code, validate, and optionally deploy.

        Parameters
        ----------
        text    : natural language behavior description
        deploy  : if True, deploy to Halo after validation
        run_sec : seconds the app runs before auto-stopping
        """
        intent    = self._parser.parse(text)
        lua, host = self._codegen.generate(intent)
        template  = get_template(intent.type)
        validation = self._validator.validate(lua, template)

        deploy_result: Optional[DeployResult] = None
        if deploy and validation.passed:
            deploy_result = await self._deployer.deploy(lua, run_sec=run_sec)

        return CompileResult(
            intent=intent,
            lua_code=lua,
            host_code=host,
            validation=validation,
            deploy_result=deploy_result,
        )

    def compile_sync(self, text: str, deploy: bool = False) -> CompileResult:
        """Synchronous wrapper for non-async callers (e.g., CLI)."""
        return asyncio.run(self.compile(text, deploy=deploy))
