# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for the DreamLayer Brain Windows tray app.

    cd host-python/packaging/windows
    pyinstaller DreamLayer.spec        # -> dist/DreamLayer/DreamLayer.exe

Prereqs (Windows):
    pip install ../..                  # the dreamlayer package + deps
    pip install pystray pywebview zeroconf cryptography pyinstaller

Windowed (no console — logs go to ~/.dreamlayer/brain.log, see
logging_setup) and one-dir (a folder the installer copies; faster startup
and Defender-friendlier than one-file self-extraction). The whole
`dreamlayer` package is bundled — the engine imports its seams lazily and
per-platform, which static analysis alone would miss — mirroring py2app's
packages=["dreamlayer"]. zeroconf + cryptography are the same starter
capabilities the .dmg bakes in (LAN discovery, Ed25519 signing); pystray
and pywebview are the Windows shell. The installer
(installer.iss) wraps dist/DreamLayer into a per-user setup exe.
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = collect_data_files("dreamlayer")     # panel assets (webp/png/woff2), py.typed

hiddenimports = (
    collect_submodules("dreamlayer")
    + [
        "pystray._win32",                    # pystray picks its backend dynamically
        "zeroconf", "ifaddr", "cryptography",
        "webview",                           # pywebview (WebView2) panel window
    ]
)

a = Analysis(
    ["..\\app_main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="DreamLayer",
    icon="dreamlayer.ico",                   # built by make_ico.py
    console=False,                           # tray appliance — no console window
    disable_windowed_traceback=False,
    upx=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="DreamLayer",
    upx=False,
)
