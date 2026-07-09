"""py2app build script for the DreamLayer Brain menu-bar app.

    cd host-python/packaging
    python setup_app.py py2app          # -> dist/DreamLayer.app

Prereqs (macOS only):
    pip install ../.                    # installs the `dreamlayer` package + deps
    pip install py2app rumps            # rumps pulls in pyobjc

Produces a menu-bar app (``LSUIElement``) — no Dock icon; a status item in the
menu bar supervises the Brain and opens the control panel. CI signs + notarizes
the result and wraps it in a .dmg (see ../../.github/workflows/build-macos-app.yml).
"""
from setuptools import setup

try:
    from dreamlayer import __version__ as VERSION
except Exception:                                   # pragma: no cover
    VERSION = "0.5.0"

APP = ["app_main.py"]

OPTIONS = {
    "argv_emulation": False,
    "iconfile": "dreamlayer.icns",                  # built from icon.png in CI
    # bundle the whole package + the GUI toolkit. PIL and numpy MUST be here
    # (not in `includes`): py2app zips `includes` into python3xx.zip, but these
    # ship vendored dylibs under a `.dylibs/` dir. Zipped, those dylibs can't be
    # reached by codesign (so notarization rejects them as unsigned) and can't be
    # dlopen'd at runtime. Listed as packages, py2app copies them unzipped onto
    # disk, where the CI signing loop signs each dylib with a secure timestamp.
    # zeroconf + cryptography are the starter capabilities baked into the DMG
    # (LAN discovery of the Brain; Ed25519 signing). Both carry native code,
    # so — like PIL/numpy — they must live in `packages` (unzipped, signable),
    # never `includes`. ifaddr is zeroconf's pure-python companion.
    "packages": ["dreamlayer", "rumps", "PIL", "numpy",
                 "zeroconf", "ifaddr", "cryptography"],
    # transitive imports py2app's static analysis tends to miss
    "includes": ["pydantic", "pydantic_core", "openai", "httpx", "httpcore",
                 "certifi", "WebKit"],   # WebKit → the native panel window
    "plist": {
        "CFBundleName": "DreamLayer",
        "CFBundleDisplayName": "DreamLayer",
        "CFBundleIdentifier": "vision.dreamlayer.brain",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSUIElement": True,                        # menu-bar appliance, no Dock icon
        "LSMinimumSystemVersion": "12.0",
        "NSHumanReadableCopyright": "© DreamLayer",
        # shown when macOS first asks to control Calendar/Contacts/Reminders
        "NSAppleEventsUsageDescription":
            "DreamLayer reads Calendar, Contacts and Reminders to build your daily brief.",
    },
}

setup(
    app=APP,
    name="DreamLayer",
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
