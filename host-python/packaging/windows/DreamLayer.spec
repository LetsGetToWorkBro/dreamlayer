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

from PyInstaller.utils.hooks import (collect_data_files, collect_submodules,
                                     collect_all)

datas = collect_data_files("dreamlayer")     # panel assets (webp/png/woff2), py.typed

# pip (+ its vendored data) is bundled so the sealed installer can add optional
# capability PACKS into its writable sidecar (%USERPROFILE%\.dreamlayer\
# site-packages) via pip --target — one-click, no source install. collect_all
# grabs pip's submodules, data (its CA bundle), and any binaries; if a build ever
# omits it the panel degrades to the honest "runs on a source install".
pip_datas, pip_binaries, pip_hidden = collect_all("pip")
datas += pip_datas

hiddenimports = (
    collect_submodules("dreamlayer")
    + pip_hidden
    + [
        "pystray._win32",                    # pystray picks its backend dynamically
        "zeroconf", "ifaddr", "cryptography",
        "webview",                           # pywebview (WebView2) panel window
        "setuptools", "wheel",               # pip's build helpers for --target installs
    ]
)

a = Analysis(
    ["..\\app_main.py"],
    pathex=[],
    binaries=pip_binaries,
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
