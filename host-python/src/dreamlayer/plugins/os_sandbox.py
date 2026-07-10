"""OS-level sandbox around the subprocess plugin jail (isolation.py).

isolation.py already runs an untrusted plugin in its own process behind a thin
RPC surface. This adds a *kernel* boundary around that process when the tools are
present — **bubblewrap** (`bwrap`) or **nsjail** — so a hostile plugin is confined
by namespaces + a read-only filesystem + no-new-privileges, not only by the
narrowness of the RPC.

It maps the capability model onto the sandbox: **no `network` capability → the
child runs in an empty network namespace** (no interfaces, no host network); the
filesystem is read-only except a private `tmpfs` at `/tmp`; the package dir is
bound read-only; PID/IPC/UTS namespaces are unshared.

Graceful by construction:
  * If no sandbox tool is installed *or a functional probe fails* (e.g.
    unprivileged user namespaces are disabled), the wrapper is empty and the
    child runs as a plain subprocess — exactly the prior behaviour.
  * `DL_SANDBOX=none` force-disables; `DL_SANDBOX=bwrap|nsjail` pins a tool;
    `DL_SANDBOX=auto` (default) uses the best available that actually works.

Roadmap (docs/SDK.md): a WASM tier (wasmtime / Pyodide) where a denied capability
is simply a WASI import the host never provides — hard memory + CPU (fuel) limits,
zero ambient authority. Not yet wired.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import sysconfig

_probe_cache: dict = {}


def _ro_binds() -> list:
    """Read-only paths the child needs to import Python + dreamlayer. Binding
    every existing sys.path entry covers an editable install's src dir."""
    paths = ["/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc"]
    paths += [sys.prefix, sys.base_prefix,
              sysconfig.get_paths().get("purelib", ""),
              sysconfig.get_paths().get("platlib", "")]
    paths += [p for p in sys.path if p]
    seen, out = set(), []
    for p in paths:
        rp = os.path.realpath(p) if p else ""
        if rp and rp not in seen and os.path.isdir(rp):
            seen.add(rp)
            out.append(rp)
    return out


def _works(tool: str) -> bool:
    """A trivial confinement that must succeed, or the tool is unusable here
    (userns disabled, missing kernel support). Cached per tool."""
    if tool in _probe_cache:
        return _probe_cache[tool]
    try:
        if tool == "bwrap":
            probe = ["bwrap", "--ro-bind", "/", "/", "--unshare-net", "true"]
        else:  # nsjail
            probe = ["nsjail", "--quiet", "-Mo", "--disable_clone_newnet",
                     "--", "/bin/true"]
        r = subprocess.run(probe, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=5)
        ok = r.returncode == 0
    except Exception:
        ok = False
    _probe_cache[tool] = ok
    return ok


def available() -> str | None:
    """The sandbox tool to use, or None to run unsandboxed. Honours DL_SANDBOX
    and only returns a tool that passes its functional probe."""
    mode = os.environ.get("DL_SANDBOX", "auto").strip().lower()
    if mode == "none":
        return None
    candidates = {"bwrap": ["bwrap"], "bubblewrap": ["bwrap"],
                  "nsjail": ["nsjail"], "auto": ["bwrap", "nsjail"]}.get(mode, [])
    for tool in candidates:
        if shutil.which(tool) and _works(tool):
            return tool
    return None


def wrapper(capabilities, package_dir) -> list:
    """A command prefix that confines the child, or ``[]`` when no sandbox tool
    is usable. Prepend it to the child's argv. `network` in `capabilities`
    keeps the network namespace shared; otherwise it is unshared (no net)."""
    tool = available()
    if tool is None:
        return []
    net = "network" in set(capabilities or [])
    pkg = os.path.realpath(str(package_dir))
    if tool == "bwrap":
        cmd = ["bwrap", "--die-with-parent", "--unshare-pid", "--unshare-ipc",
               "--unshare-uts", "--new-session",
               "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
               "--chdir", "/"]
        for p in _ro_binds():
            cmd += ["--ro-bind", p, p]
        cmd += ["--ro-bind-try", pkg, pkg]
        if not net:
            cmd += ["--unshare-net"]
        return cmd
    # nsjail: mount-only mode, read-only rootfs bind, optional net unshare
    cmd = ["nsjail", "--quiet", "-Mo", "--rlimit_as", "1024",
           "--disable_clone_newuser", "--chroot", "/", "--"]
    if not net:
        cmd = cmd[:-1] + ["--disable_clone_newnet", "--"]
    return cmd


def describe() -> str:
    tool = available()
    return f"os-sandbox: {tool}" if tool else "os-sandbox: none (plain subprocess)"
