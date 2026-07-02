"""reality_compiler/validator.py — Emulator-based pre-flight validation.

Runs generated Lua through HaloEmulator, injects the template test_spec
events, and asserts the display has visible content.

Returns a ValidationResult with pass/fail + log.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .emulator import HaloEmulator
from .template_library import BehaviorTemplate


@dataclass
class ValidationResult:
    passed: bool
    behavior: str
    bright_pixels: int
    events_injected: list[str] = field(default_factory=list)
    error: Optional[str] = None
    warnings: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        parts = [f"[{status}] {self.behavior}  bright_px={self.bright_pixels}"]
        if self.error:
            parts.append(f"  error: {self.error}")
        for w in self.warnings:
            parts.append(f"  warn:  {w}")
        return "\n".join(parts)


class EmulatorValidator:
    """Validates generated Lua code using HaloEmulator."""

    # Minimum bright pixel estimate to consider display "active"
    MIN_BRIGHT_PIXELS = 1

    def validate(
        self,
        lua_code: str,
        template: BehaviorTemplate,
        battery_level: int = 75,
        wait_real_sec: float = 0.05,
    ) -> ValidationResult:
        """Run *lua_code* in the emulator and check display output.

        Parameters
        ----------
        lua_code       : generated Lua string
        template       : the BehaviorTemplate used (for test_spec)
        battery_level  : mock battery % injected into emulator
        wait_real_sec  : real seconds to wait after event injection
        """
        spec = template.test_spec
        emu = HaloEmulator(battery_level=battery_level)
        emu.load_lua(lua_code)
        events_injected: list[str] = []
        warnings: list[str] = []

        try:
            emu.start()
            emu.wait(timeout=wait_real_sec)

            inject = spec.get("inject")
            if inject == "double_click":
                emu.inject_double_click()
                events_injected.append("double_click")
            elif inject == "single_click":
                emu.inject_single_click()
                events_injected.append("single_click")
            elif inject == "bluetooth":
                data = spec.get("bluetooth_data", b"\x01")
                emu.inject_bluetooth(data)
                events_injected.append("bluetooth")

            emu.wait(timeout=wait_real_sec)

            bright = emu.bright_pixel_count()
            texts = emu.shown_texts()

            # Structural checks (don't require Lua execution)
            if "${" in lua_code:
                warnings.append("Unsubstituted template variables found in Lua code")

            assert_bright = spec.get("assert_bright", True)

            # When lupa is unavailable we can only do structural checks
            try:
                import lupa  # noqa: F401
                lupa_available = True
            except ImportError:
                lupa_available = False
                warnings.append("lupa not installed — Lua execution skipped; structural checks only")

            if lupa_available and assert_bright and bright < self.MIN_BRIGHT_PIXELS:
                # Check if display has any text at all
                if not texts:
                    return ValidationResult(
                        passed=False,
                        behavior=template.name,
                        bright_pixels=bright,
                        events_injected=events_injected,
                        error="Display shows no content after event injection",
                        warnings=warnings,
                    )

            return ValidationResult(
                passed=True,
                behavior=template.name,
                bright_pixels=bright,
                events_injected=events_injected,
                warnings=warnings,
            )

        except Exception as exc:
            return ValidationResult(
                passed=False,
                behavior=template.name,
                bright_pixels=0,
                events_injected=events_injected,
                error=str(exc),
                warnings=warnings,
            )
        finally:
            emu.stop()
