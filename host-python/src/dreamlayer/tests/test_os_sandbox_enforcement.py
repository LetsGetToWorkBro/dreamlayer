"""test_os_sandbox_enforcement.py — the jail tier, asserted from INSIDE the jail.

`test_os_sandbox.py` pins argv *construction*: it proves `--unshare-net` was put
on the command line when the `network` capability was withheld, and that
`--clearenv` plus the five `--setenv` pairs were put there too. That is a lint
over a list of strings. It cannot tell whether the kernel honoured any of them,
so the whole tier could be inert without one assertion there moving — the same
shape of hole as 105 wasm tests that were green by skip (#630).

This runs the real thing. A one-file plugin package is launched exactly the way
`isolation.py._child_argv` launches one — `os_sandbox.wrapper(caps, pkg)` in
front of `python -m dreamlayer.plugins.sandbox_child <pkg> <caps>` — and from
inside the running child it reaches for the network by the route
`validate.py:22-28` documents as a KNOWN static-scan bypass::

    __builtins__["__import__"]("socket")

That choice is the point. The AST screen cannot see this reach, so whatever
refuses it is the kernel, not the lint — which is the claim the OS-sandbox tier
makes and the one nothing was checking.

**The probe transmits nothing.** `connect()` on a SOCK_DGRAM socket is a route
lookup plus a stored peer address; no datagram leaves (measured: Udp
OutDatagrams unchanged across a bare connect). The target is 192.0.2.1
(RFC 5737 TEST-NET-1) and the port is discard/9. So this test is inert on the
wire in both directions and needs no `allow_egress` mark.

That last point deserves its own sentence, because `allow_egress` is what the
suite's egress tripwire normally demands of a test naming a public address: the
tripwire in `tests/conftest.py` is a process-wide audit hook, and this probe runs
two processes down, in the jailed grandchild, where no such hook exists. It is
structurally blind here — so its silence is not evidence, and the measurement
above is what carries the claim instead.

Two runs of the SAME package, differing only in the declared capability:

  * no `network` → the child's own JSON line reports the kernel's ENETUNREACH.
  * `network`    → the identical probe finds a route and the plugin registers.

The second run is what makes the first one mean something. A probe that failed
in every environment would satisfy a one-sided test while proving nothing; here
the only difference between refused and permitted is the capability, so the
capability is what did it.

**The second probe is the environment**, and it runs through the same machinery:
a one-file package whose `register()` compares the environment it can actually
see against the exact set `os_sandbox._JAIL_ENV` recreates, reporting every key
that differs in EITHER direction. Both directions are the point. Counting only
the keys that leaked in from the host is satisfied just as happily by a jail
that hands the child no environment at all, so such a test stays green while the
allowlist is gutted and leaves argv construction as the only thing objecting —
and #424 is explicit about what that is worth: it "proves the command was
built, not that the boundary holds".

**Nothing here asserts a return code, deliberately.** A jailed child that dies of
an import error, a missing interpreter, an OOM kill or a bwrap setup failure
exits non-zero exactly like one that was correctly refused; `returncode != 0` is
the defect this file exists to replace, not a weaker version of the check.

The assertions are not interchangeable, and it is worth being exact about which
one catches what. `argv[0] == "bwrap"` and the `--unshare-net` / `--clearenv`
checks catch *the flag was dropped* — the same direction `test_os_sandbox.py`
already covers. Only the protocol-line, the errno and the environment-mismatch
checks catch *the flag is present and the boundary is inert*, which is the
direction a construction test cannot see and the reason this file exists.

And what is NOT pinned here, so the file is not read for more than it does: the
nsjail branch of `wrapper()` — every test below runs the bwrap branch — and the
PID/IPC/UTS unsharing, which reaches the command line and is asserted from
inside nowhere.
"""
from __future__ import annotations

import errno
import json
import os
import subprocess
import sys

import pytest

from dreamlayer.plugins import os_sandbox

# Errnos that mean "this namespace has no route off itself". Anything else —
# EACCES, ETIMEDOUT, a NameError, an ImportError — is a different failure and
# must not be read as a capability denial.
NO_ROUTE = (errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ENETDOWN)

# The untrusted network plugin. `register()` runs inside the jail, so the reach
# happens in there and its outcome leaves over the child's own protocol on
# stdout — the only channel out. Not because the jail is read-only: bwrap's new
# root is a writable tmpfs, and measured through this very wrapper, `/` and
# `/tmp` accept writes while the bound host paths give EROFS. It is the only channel out
# because everything writable in there is private to the child's mount namespace
# and gone when it exits. The OSError is deliberately NOT caught: sandbox_child
# turns a raising register() into {"ok": false, "error": repr(exc)} on stdout.
PROBE_SRC = '''
def make():
    return _NetProbe()


class _NetProbe:
    name = "netprobe"
    facet = "own"

    def register(self, ctx):
        socket = __builtins__["__import__"]("socket")   # validate.py:25 bypass
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("192.0.2.1", 9))   # route lookup only; sends nothing
        finally:
            sock.close()
        ctx.add_object_provider(self)

    def matches(self, sighting):
        return False

    def build(self, sighting):
        return []
'''

# The untrusted environment plugin, run through the same host. It registers one
# provider per environment key that is wrong in EITHER direction — present when
# nothing should have put it there, or absent when `_JAIL_ENV` promised it — so
# a count of zero is the whole verdict and the `meta` op names the offenders.
#
# The five names are spelled out here rather than read from `os_sandbox._JAIL_ENV`
# at run time, and that is the whole point: a probe generated from the value it
# is checking cannot notice that value being emptied. It would pass against a
# jail that hands the child nothing, which is the check this replaces.
#
# `PWD` is bwrap's own: it sets it from `--chdir`, and the plugin neither sets
# nor forbids it. Excluding it from the comparison rather than requiring it
# keeps this test about what os_sandbox controls, and stops a bwrap release that
# stopped setting PWD from reading as an environment leak.
ENV_PROBE_SRC = '''
_REQUIRED = {"HOME", "LANG", "LC_ALL", "PATH", "TMPDIR"}
_TOOL_OWNED = {"PWD"}


def make():
    return _EnvProbe()


class _Marker:
    facet = "own"

    def __init__(self, name):
        self.name = name


class _EnvProbe:
    def register(self, ctx):
        os = __builtins__["__import__"]("os")   # as PROBE_SRC reaches, above
        for name in sorted((set(os.environ) ^ _REQUIRED) - _TOOL_OWNED):
            ctx.add_object_provider(_Marker(name))
'''


@pytest.fixture(autouse=True)
def _bwrap_or_say_why():
    """A working bwrap, or an explanation that is never a bare skip.

    `DL_SANDBOX=bwrap` is a promise the operator made about the environment (the
    CI leg added for this file makes it). When the promise is not kept this
    FAILS: a skip that fires on every runner is the defect one layer up, and an
    absent sandbox on a leg that claimed one is a real finding about the
    machine, not a reason to go quiet.

    Unpinned, a contributor without bwrap gets an honest skip naming the tool
    that was found and the pin that turns the skip into a run. bwrap
    specifically, rather than whatever `available()` returns: it is the tool the
    CI leg installs, and the flags this file asserts on (`--unshare-net`,
    `--clearenv`) are the bwrap branch of `wrapper()`. The nsjail branch builds a
    different command — it widens an environment nsjail already emptied, rather
    than clearing an inherited one — and is not exercised here.
    """
    tool = os_sandbox.available()
    if tool == "bwrap":
        return
    pinned = os.environ.get("DL_SANDBOX", "auto").strip().lower()
    if pinned in ("bwrap", "bubblewrap"):
        pytest.fail(
            f"DL_SANDBOX={pinned!r} promises a working bwrap, but "
            f"os_sandbox.available() is {tool!r}: bwrap is missing, or its "
            "functional probe failed (unprivileged user namespaces disabled?). "
            "That is an environment failure to fix, not a test to skip.")
    pytest.skip(
        f"os_sandbox.available() is {tool!r}; this asserts kernel enforcement "
        "and needs a working bwrap. Install bubblewrap and set DL_SANDBOX=bwrap "
        "to make it run — and fail if it cannot.")


def _write_pkg(root, src=PROBE_SRC, name="netprobe"):
    """The same package shape as `_pkg` in test_plugin_v2.py, the sibling that
    drives this very host: `plugin.py` + `plugin:make`, `"api"` as a string.
    One deliberate difference — `requires` is empty where the sibling names the
    capability its plugin needs, because the plugin here is meant to declare
    nothing and reach anyway. It changes nothing either way: `sandbox_child`
    takes the granted set from argv, and never reads `requires`.

    `src`/`name` default to the network probe; every other probe goes through
    here too rather than restating the layout beside it."""
    pkg = root / name
    pkg.mkdir()
    (pkg / "plugin.py").write_text(src)
    (pkg / "manifest.json").write_text(json.dumps(
        {"name": name, "version": "0.1.0", "entry": "plugin:make",
         "api": "2", "requires": []}))
    return pkg


def _run_jailed(pkg, caps, ops=("init",)):
    """Launch the child the way isolation.py does; return (argv, first JSON
    line it emitted or None, the completed process).

    `ops` are the protocol ops written to the child's stdin, in order, and the
    reply returned is the first one's. Later replies stay in `proc.stdout`,
    which `_diag` prints verbatim — that is how the environment test's `meta`
    reply carries the offending variable NAMES into a failure message."""
    argv = os_sandbox.wrapper(caps, pkg) + [
        sys.executable, "-m", "dreamlayer.plugins.sandbox_child",
        str(pkg), json.dumps(caps)]
    stdin = "".join(json.dumps({"op": op}) + "\n" for op in ops)
    proc = subprocess.run(argv, input=stdin, capture_output=True,
                          text=True, timeout=120)
    line = next((ln for ln in proc.stdout.splitlines() if ln.strip()), "")
    try:
        reply = json.loads(line)
    except ValueError:
        reply = None
    return argv, reply, proc


def _diag(argv, proc):
    return (f"\nargv: {argv}\nrc: {proc.returncode}"
            f"\nstdout: {proc.stdout!r}\nstderr: {proc.stderr!r}")


def test_denied_network_capability_is_refused_by_the_kernel(tmp_path):
    pkg = _write_pkg(tmp_path)
    argv, reply, proc = _run_jailed(pkg, [])

    # The child really was jailed with the network withheld — not run bare
    # because `available()` quietly returned None.
    assert argv[0] == "bwrap", _diag(argv, proc)
    assert "--unshare-net" in argv, _diag(argv, proc)

    # A parseable protocol line is evidence of exactly one thing, and it is
    # worth not claiming more: the child cleared bwrap setup and exec and
    # reached sandbox_child.main(). A bwrap setup failure, a missing
    # interpreter or an OOM kill produces no such line — those write to stderr
    # and die, which is precisely the confusion a return-code assertion cannot
    # resolve. It does NOT prove register() was entered: sandbox_child wraps
    # _load_plugin and register in one try and emits the same shape for a bad
    # manifest or a source that raises at exec. Excluding those is the errno
    # assertion's job, below — none of them repr as OSError(ENETUNREACH).
    assert reply is not None, (
        "the child emitted no protocol line, so it never reached main(); "
        "this is a broken jail, not a refusal" + _diag(argv, proc))
    assert reply.get("ok") is False, _diag(argv, proc)

    # And the refusal is the specific one: the kernel had no route out of the
    # empty network namespace. repr(OSError) carries the errno, so an
    # ImportError, a NameError or any other OSError fails here.
    err = reply.get("error", "")
    assert any(f"OSError({e}," in err for e in NO_ROUTE), (
        f"expected a no-route OSError {NO_ROUTE}, got {err!r}" + _diag(argv, proc))


def test_granted_network_capability_lets_the_same_probe_through(tmp_path):
    pkg = _write_pkg(tmp_path)
    argv, reply, proc = _run_jailed(pkg, ["network"])

    assert argv[0] == "bwrap", _diag(argv, proc)
    assert "--unshare-net" not in argv, _diag(argv, proc)
    assert reply is not None, _diag(argv, proc)

    # This is the control, and its failure mode matters more than its success.
    # If the probe reports no route HERE, the host has none either — and then
    # the refusal asserted above proves nothing about the jail, because the
    # environment would have produced it unaided. So this must fail, loudly,
    # rather than skip: a vacuous denial test is the thing being fixed.
    err = reply.get("error", "")
    assert not any(f"OSError({e}," in err for e in NO_ROUTE), (
        "the probe found no route even with `network` GRANTED, so this host "
        "has no route off-box and the denial test above cannot distinguish "
        "the jail from the environment" + _diag(argv, proc))
    assert reply.get("ok") is True, _diag(argv, proc)
    assert reply.get("providers") == 1, _diag(argv, proc)


def test_the_host_is_read_only_and_the_private_root_is_not(tmp_path):
    """What the jail's filesystem actually does, asserted rather than described.

    The module docstring used to say "the filesystem is read-only except a
    private tmpfs at /tmp". It is not: bwrap's new root is itself a tmpfs and
    takes writes, and only the `--ro-bind` mounts refuse (#632). The security
    conclusion is unchanged — everything writable is private to the child's
    mount namespace and gone when it exits — but that was the sentence somebody
    would rely on when reasoning about where a hostile plugin can leave a file.

    So this pins both halves. The EROFS half is the one with security weight:
    if a host bind ever became writable, a plugin could modify the code it is
    about to import. The writable half exists so the docstring cannot quietly
    drift back to the tidier claim that was wrong.
    """
    probe = (
        "import errno, json\n"
        "out = {}\n"
        "for p in ('/zz', '/tmp/zz', '/usr/zz', '/etc/zz'):\n"
        "    try:\n"
        "        open(p, 'w').write('x')\n"
        "        out[p] = 'wrote'\n"
        "    except OSError as e:\n"
        "        out[p] = e.errno\n"
        "print(json.dumps(out))\n")
    argv = os_sandbox.wrapper([], tmp_path) + [sys.executable, "-c", probe]
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    assert proc.stdout.strip(), (
        "the probe produced no output, so it never ran" + _diag(argv, proc))
    got = json.loads(proc.stdout.splitlines()[-1])

    # The half that carries the security claim: nothing bound in from the host
    # may be written, or a plugin could rewrite the code it is about to import.
    for path in ("/usr/zz", "/etc/zz"):
        assert got[path] == errno.EROFS, (
            f"{path} is writable inside the jail (got {got[path]!r}); a host "
            f"bind must be read-only" + _diag(argv, proc))

    # The half that keeps the docstring honest.
    for path in ("/zz", "/tmp/zz"):
        assert got[path] == "wrote", (
            f"{path} refused a write ({got[path]!r}). That may be a HARDENING "
            f"rather than a regression — but the module docstring says the "
            f"private root and /tmp accept writes, so change the docstring in "
            f"the same commit" + _diag(argv, proc))


def test_a_ci_leg_actually_runs_this_file():
    """The coupling this file asked for in its own PR.

    Everything above skips unless a working bwrap is present, and bwrap is
    installed by exactly one step in pytest.yml. Delete that step and this
    entire file goes quietly back to skipping everywhere, with no assertion
    moving anywhere — which is the shape of hole it was written against, and
    the shape that left 105 wasm tests green by skip until #630.

    A comment in the workflow saying so is a comment. This fails.

    Anchored on the two things that make the leg real — the install and the
    pin — rather than on the step's name, which is prose somebody may reword.
    """
    import pathlib
    import re

    wf = (pathlib.Path(__file__).resolve().parents[4]
          / ".github" / "workflows" / "pytest.yml").read_text(encoding="utf-8")
    live = [ln for ln in wf.splitlines() if not ln.lstrip().startswith("#")]
    body = "\n".join(live)

    assert re.search(r"apt-get install .*\bbubblewrap\b", body), (
        "no CI step installs bubblewrap, so every test in this file skips: "
        "the OS-sandbox tier's enforcement runs in no environment again")
    # `[\s\S]` rather than `[^\n]`: the invocation is split over a backslash
    # continuation, and a newline-bounded pattern silently matches nothing —
    # which would make this coupling test the very thing it guards against.
    assert re.search(r"DL_SANDBOX=bwrap\s+pytest[\s\S]{0,200}?"
                     r"test_os_sandbox_enforcement\.py", body), (
        "no CI step runs this file with DL_SANDBOX=bwrap. Without the pin the "
        "fixture SKIPS when bwrap is missing instead of failing, so a runner "
        "that lost bubblewrap would go quiet rather than red")


def test_the_jail_environment_is_exactly_the_one_os_sandbox_builds(monkeypatch,
                                                                   tmp_path):
    """The environment boundary asserted from inside it, in BOTH directions.

    What is pinned: the jailed child sees `_JAIL_ENV`'s five variables and no
    other key, `PWD` aside (bwrap sets that one from `--chdir`; the comment on
    ENV_PROBE_SRC says why it is excluded rather than required). A host variable
    that crossed the boundary fails this, and so does one of the five going
    missing — the second half is what a leak count alone cannot see, and it is
    the half that notices `_JAIL_ENV` being emptied.

    The host sentinel keeps the first half honest on a machine whose own
    environment is unusually sparse: without it, a `--clearenv` that had been
    dropped could still leave nothing to find.

    The values are NOT pinned here, only the key set; `test_os_sandbox.py` pins
    the values on the command line. Crossing the jail with a name per variable
    is what the object-provider protocol carries cheaply, and a name is what a
    reader of a failure needs first.
    """
    monkeypatch.setenv("DREAMLAYER_TEST_HOST_ENV_LEAK", "must-not-enter-jail")
    pkg = _write_pkg(tmp_path, ENV_PROBE_SRC, "envprobe")

    argv, reply, proc = _run_jailed(pkg, [], ops=("init", "meta"))

    # The flag reached the command line and the child really was jailed — the
    # same direction test_os_sandbox.py covers, restated here so a failure below
    # cannot be blamed on an unsandboxed run.
    assert argv[0] == "bwrap", _diag(argv, proc)
    assert "--clearenv" in argv, _diag(argv, proc)

    assert reply is not None, (
        "the child emitted no protocol line, so it never reached main(); "
        "this is a broken jail, not an environment verdict" + _diag(argv, proc))
    assert reply.get("ok") is True, _diag(argv, proc)
    assert reply.get("providers") == 0, (
        "the jailed child's environment is not the one os_sandbox builds. Each "
        "provider in the `meta` reply below names a key that either leaked in "
        "from the host or is one of _JAIL_ENV that never arrived"
        + _diag(argv, proc))
