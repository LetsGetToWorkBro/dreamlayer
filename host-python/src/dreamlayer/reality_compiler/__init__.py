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
from .compiler import RealityCompiler, CompileResult
from .intent_parser import IntentParser
from .schema import (
    BehaviorIntent, RoundTimerIntent, OvertimeTimerIntent,
    StopwatchIntent, IntervalTimerIntent, SimpleCounterIntent,
    BatteryWarningIntent, TeleprompterIntent, CoachingCueIntent,
    PointsMarkerIntent, NextClassIntent, TextSubtitlesIntent,
    HabitReminderIntent, ReactTimerIntent, GestureRepeaterIntent,
    SpeakerIndicatorIntent, ValidationError,
)
from .codegen import CodeGenerator
from .emulator import HaloEmulator
from .validator import EmulatorValidator
from .deployer import HaloDeployer

__all__ = [
    "RealityCompiler", "CompileResult",
    "IntentParser",
    "BehaviorIntent", "RoundTimerIntent", "OvertimeTimerIntent",
    "StopwatchIntent", "IntervalTimerIntent", "SimpleCounterIntent",
    "BatteryWarningIntent", "TeleprompterIntent", "CoachingCueIntent",
    "PointsMarkerIntent", "NextClassIntent", "TextSubtitlesIntent",
    "HabitReminderIntent", "ReactTimerIntent", "GestureRepeaterIntent",
    "SpeakerIndicatorIntent", "ValidationError",
    "CodeGenerator",
    "HaloEmulator",
    "EmulatorValidator",
    "HaloDeployer",
]
