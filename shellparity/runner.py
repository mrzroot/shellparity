"""Spawn shells in the different startup modes and collect probe snapshots."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional, Sequence

from .probe import build_probe
from .snapshot import failed_snapshot, mask_text, parse_records, snapshot_from_records

SUPPORTED_SHELLS = ("bash", "zsh", "sh")
MODES = ("human", "login", "interactive", "plain", "bare")

MODE_HELP = {
    "human": "login + interactive, on a pseudo-terminal (what your terminal app starts)",
    "login": "login shell, no tty (like `-lc`)",
    "interactive": "interactive shell, no tty (like `-ic`)",
    "plain": "non-login, non-interactive (`-c`, what most agents run)",
    "bare": "like plain, but with an almost empty environment (HOME only)",
}

# Session variables copied from the current process into every probed shell.
# Everything else must come from the shell's own startup files.
SESSION_VARS = ("HOME", "USER", "LOGNAME", "LANG", "LANGUAGE", "TZ")
DEFAULT_PATH = "/usr/bin:/bin"


def find_shell(name_or_path: str) -> Optional[str]:
    if os.sep in name_or_path:
        return name_or_path if os.access(name_or_path, os.X_OK) else None
    return shutil.which(name_or_path)


def shell_basename(path: str) -> str:
    base = os.path.basename(path)
    return base if base in SUPPORTED_SHELLS else base


def available_shells() -> Dict[str, str]:
    found = {}
    for n in SUPPORTED_SHELLS:
        p = shutil.which(n)
        if p:
            found[n] = p
    return found


def base_environment(shell_path: str, inherit: bool = False,
                     home: Optional[str] = None,
                     extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Environment the probed shells start from (before their rc files run)."""
    if inherit:
        env = dict(os.environ)
    else:
        env = {k: os.environ[k] for k in SESSION_VARS if k in os.environ}
        env["PATH"] = DEFAULT_PATH
    if home:
        env["HOME"] = home
    env["SHELL"] = shell_path
    env.update(extra or {})
    return env


def build_argv(mode: str, shell_path: str, probe_file: str) -> List[str]:
    cmd = ". '%s'" % probe_file.replace("'", "'\\''")
    if mode == "human":
        return [shell_path, "-l", "-i", "-c", cmd]
    if mode == "login":
        return [shell_path, "-l", "-c", cmd]
    if mode == "interactive":
        return [shell_path, "-i", "-c", cmd]
    if mode in ("plain", "bare"):
        return [shell_path, "-c", cmd]
    raise ValueError("unknown mode %r" % mode)


def _kill_group(proc: "subprocess.Popen[bytes]") -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass


def _run_pty(argv: Sequence[str], env: Dict[str, str], timeout: float, cwd: str):
    import fcntl
    import pty
    import select
    import struct
    import termios

    master, slave = pty.openpty()
    try:
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
    except OSError:
        pass

    def _child_setup() -> None:  # runs in the child between fork and exec
        os.setsid()
        try:
            fcntl.ioctl(0, termios.TIOCSCTTY, 1)
        except OSError:
            pass

    proc = subprocess.Popen(list(argv), stdin=slave, stdout=slave, stderr=slave,
                            env=env, cwd=cwd, preexec_fn=_child_setup, close_fds=True)
    os.close(slave)
    out = bytearray()
    answered_newuser = False
    deadline = time.monotonic() + timeout
    timed_out = False
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            ready, _, _ = select.select([master], [], [], min(0.2, remaining))
            if ready:
                try:
                    chunk = os.read(master, 65536)
                except OSError:  # EIO: the child closed the pty
                    chunk = b""
                if chunk:
                    out.extend(chunk)
                    if not answered_newuser and b"zsh-newuser-install" in out:
                        # A zsh with no startup files at all offers a setup wizard on a
                        # tty. Answer "q" (quit and do nothing; nothing is written).
                        answered_newuser = True
                        try:
                            os.write(master, b"q")
                        except OSError:
                            pass
                    continue
                if proc.poll() is not None:
                    break
            if proc.poll() is not None and not ready:
                break
    finally:
        if timed_out:
            _kill_group(proc)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
        os.close(master)
    return proc.returncode, bytes(out), timed_out


def _run_pipe(argv: Sequence[str], env: Dict[str, str], timeout: float, cwd: str):
    proc = subprocess.Popen(list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env, cwd=cwd,
                            start_new_session=True)
    try:
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, out + err, False
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        out, err = proc.communicate()
        return proc.returncode, out + err, True


def run_mode(mode: str, shell_path: str, probe_file: str, workdir: str,
             base_env: Dict[str, str], timeout: float = 30.0,
             cwd: Optional[str] = None) -> Dict[str, Any]:
    """Run the probe once in ``mode`` and return a snapshot (never raises)."""
    shell = shell_basename(shell_path)
    out_file = os.path.join(workdir, "out-%s.txt" % mode)
    with open(out_file, "w"):
        pass
    env = dict(base_env)
    env["SP_OUT"] = out_file
    if mode == "bare":
        env = {"HOME": base_env.get("HOME", os.path.expanduser("~")), "SP_OUT": out_file}
    if mode == "human":
        env.setdefault("TERM", "xterm-256color")
    argv = build_argv(mode, shell_path, probe_file)
    t0 = time.monotonic()
    try:
        if mode == "human":
            if sys.platform == "win32":
                raise OSError("pseudo-terminals are not available on Windows")
            code, output, timed_out = _run_pty(argv, env, timeout, cwd or workdir)
        else:
            code, output, timed_out = _run_pipe(argv, env, timeout, cwd or workdir)
    except OSError as exc:
        return failed_snapshot(mode, shell, "could not start %s: %s" % (shell_path, exc))
    elapsed = time.monotonic() - t0
    try:
        with open(out_file, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        text = ""
    rec = parse_records(text)
    snap = snapshot_from_records(mode, shell, rec)
    snap["elapsed"] = round(elapsed, 2)
    snap["exit_code"] = code
    tail = output.decode("utf-8", errors="replace").strip()
    snap["stderr_tail"] = mask_text(tail[-300:]) if not snap["ok"] else ""
    if not snap["ok"]:
        if timed_out:
            snap["error"] = ("timed out after %ss (an rc file may be waiting for input; "
                             "use --timeout to raise the limit)" % int(timeout))
        elif not rec:
            snap["error"] = ("probe produced no data (exit %s); a startup file may exit, "
                             "exec another shell, or the shell rejected the flags" % code)
        else:
            snap["error"] = "probe stopped early (exit %s)" % code
    return snap


def run_modes(shell_path: str, modes: Sequence[str] = MODES, *, probe: Optional[str] = None,
              extra_tools: Optional[Sequence[str]] = None,
              inherit_env: bool = False, home: Optional[str] = None,
              extra_env: Optional[Dict[str, str]] = None,
              timeout: float = 30.0, cwd: Optional[str] = None,
              only_tools: Optional[Sequence[str]] = None) -> Dict[str, Dict[str, Any]]:
    """Run every requested mode. All scratch files live in one temp dir."""
    probe_text = probe if probe is not None else build_probe(extra_tools, only_tools)
    results: Dict[str, Dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="shellparity-") as work:
        probe_file = os.path.join(work, "probe.sh")
        with open(probe_file, "w", encoding="utf-8") as fh:
            fh.write(probe_text)
        env = base_environment(shell_path, inherit_env, home, extra_env)
        for mode in modes:
            results[mode] = run_mode(mode, shell_path, probe_file, work, env, timeout,
                                     cwd=cwd or os.getcwd())
    return results
