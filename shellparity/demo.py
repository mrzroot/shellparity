"""Offline demo: fake environments, no network, nothing outside a temp dir.

``live``     builds a throw-away HOME (fake nvm node, proxies and locale defined only
             in .bashrc, an SSH agent socket, git signing) and runs the REAL probe
             against bash with that HOME.
``scripted`` skips the shells and feeds hand-written snapshots to the same
             compare/advise code. Deterministic on every machine (used by tests and
             as a fallback when bash is missing).
"""

from __future__ import annotations

import os
import shutil
import socket
import stat
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

from .advise import AdviceContext
from .core import analyze_snapshots
from .runner import run_modes
from .snapshot import snapshot_from_records

DEMO_HOME_ALIAS = "/home/demo"
DEMO_TOOLS = ["node", "npm", "python3", "git", "curl"]

BASHRC = '''# ~/.bashrc  (fake demo file)
case $- in
    *i*) ;;
      *) return;;
esac

export NVM_DIR="$HOME/.nvm"
export PATH="$HOME/.nvm/versions/node/v22.4.0/bin:$HOME/.local/bin:$PATH"

export HTTPS_PROXY="http://demo:secret@127.0.0.1:10809"
export no_proxy="localhost,127.0.0.1"

export LANG=@@LOCALE@@
export EDITOR=vim
export OPENAI_API_KEY="sk-demo-not-a-real-key"
export SSH_AUTH_SOCK="$HOME/.ssh/agent.sock"
export GPG_TTY=$(tty 2>/dev/null)

alias ll='ls -l'
'''
BASH_PROFILE = '# ~/.bash_profile (fake demo file)\n[ -f ~/.bashrc ] && . ~/.bashrc\n'
GITCONFIG = '''[user]
    name = Demo User
    email = demo@example.com
[commit]
    gpgsign = true
'''


def _write_exec(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def build_fake_home(base: str) -> str:
    home = os.path.join(base, "home")
    os.makedirs(home)
    locale = "en_US.UTF-8" if sys.platform == "darwin" else "C.UTF-8"
    with open(os.path.join(home, ".bashrc"), "w") as fh:
        fh.write(BASHRC.replace("@@LOCALE@@", locale))
    with open(os.path.join(home, ".bash_profile"), "w") as fh:
        fh.write(BASH_PROFILE)
    with open(os.path.join(home, ".gitconfig"), "w") as fh:
        fh.write(GITCONFIG)
    nvm_bin = os.path.join(home, ".nvm", "versions", "node", "v22.4.0", "bin")
    _write_exec(os.path.join(nvm_bin, "node"), "#!/bin/sh\necho v22.4.0\n")
    _write_exec(os.path.join(nvm_bin, "npm"), "#!/bin/sh\necho 10.8.1\n")
    os.makedirs(os.path.join(home, ".ssh"))
    return home


def run_live(shell_path: str, timeout: float = 30.0) -> Tuple[Dict[str, Any], str]:
    """Run the real flow against a fake home. Returns (result, path-alias map text)."""
    # Keep the base path short: unix socket paths are limited to ~104 bytes.
    base = tempfile.mkdtemp(prefix="sp-demo-", dir="/tmp" if os.path.isdir("/tmp") else None)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        home = build_fake_home(base)
        sock.bind(os.path.join(home, ".ssh", "agent.sock"))
        snaps = run_modes(shell_path, ["human", "plain", "login", "interactive", "bare"],
                          home=home, extra_env={"LANG": "C", "USER": "demo", "LOGNAME": "demo"},
                          timeout=timeout, cwd=home,
                          only_tools=DEMO_TOOLS)
        res = analyze_snapshots(snaps, os.path.basename(shell_path), shell_path, "plain", home)
        res["demo"] = "live"
        _alias_paths(res, home)
        return res, home
    finally:
        sock.close()
        shutil.rmtree(base, ignore_errors=True)


def _alias_paths(obj: Any, home: str) -> Any:
    """Rewrite the temp home to /home/demo everywhere (in place) for stable output."""
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            obj[k] = _alias_paths(v, home)
        return obj
    if isinstance(obj, list):
        for i, v in enumerate(obj):
            obj[i] = _alias_paths(v, home)
        return obj
    if isinstance(obj, str):
        return obj.replace(home, DEMO_HOME_ALIAS)
    if hasattr(obj, "__dataclass_fields__"):
        for name in obj.__dataclass_fields__:
            if name == "present":
                continue
            setattr(obj, name, _alias_paths(getattr(obj, name), home))
    return obj


# ------------------------------------------------------------------ scripted

def _rec(**kw: str) -> Dict[str, str]:
    return {k.replace("__", ":"): v for k, v in kw.items()}


def _base_records() -> Dict[str, str]:
    return {
        "tty0": "0", "tty1": "0", "tty2": "0", "flags": "hB", "shellver": "5.2.21(1)-release",
        "path": "/usr/local/bin:/usr/bin:/bin",
        "envnames": "HOME PATH LANG USER", "charmap": "UTF-8", "persian_chars": "4",
        "aliases": "0", "umask": "0022", "ulimit_n": "1024", "tz_abbr": "+0330", "done": "1",
        "var:HOME": "/home/demo", "var:LANG": "C.UTF-8",
        "tool:git:where": "/usr/bin/git", "tool:git:rc": "0", "tool:git:ver": "git version 2.43.0",
        "tool:curl:where": "/usr/bin/curl", "tool:curl:rc": "0", "tool:curl:ver": "curl 8.5.0",
        "git:user.name": "Demo User", "git:user.email": "demo@example.com",
        "git:commit.gpgsign": "true",
    }


def scripted_snapshots() -> Dict[str, Dict[str, Any]]:
    h = _base_records()
    h.update({
        "tty0": "1", "tty1": "1", "tty2": "1", "flags": "himBHs",
        "path": "/home/demo/.nvm/versions/node/v22.4.0/bin:/home/demo/.local/bin:/usr/local/bin:/usr/bin:/bin",
        "envnames": "HOME PATH LANG USER NVM_DIR HTTPS_PROXY no_proxy EDITOR OPENAI_API_KEY "
                    "SSH_AUTH_SOCK GPG_TTY TERM",
        "aliases": "1",
        "var:NVM_DIR": "/home/demo/.nvm", "var:HTTPS_PROXY": "http://demo:secret@127.0.0.1:10809",
        "var:no_proxy": "localhost,127.0.0.1", "var:EDITOR": "vim",
        "var:SSH_AUTH_SOCK": "/home/demo/.ssh/agent.sock", "ssh_sock_ok": "1",
        "var:GPG_TTY": "/dev/pts/3", "var:TERM": "xterm-256color",
        "tool:node:where": "/home/demo/.nvm/versions/node/v22.4.0/bin/node",
        "tool:node:rc": "0", "tool:node:ver": "v22.4.0",
        "tool:npm:where": "/home/demo/.nvm/versions/node/v22.4.0/bin/npm",
        "tool:npm:rc": "0", "tool:npm:ver": "10.8.1",
    })
    a = _base_records()
    a.update({
        "tool:python3:where": "/usr/bin/python3", "tool:python3:rc": "0",
        "tool:python3:ver": "Python 3.11.2",
        "persian_chars": "8", "charmap": "ANSI_X3.4-1968",
        "var:LANG": "C",
    })
    h.update({"tool:python3:where": "/usr/bin/python3", "tool:python3:rc": "0",
              "tool:python3:ver": "Python 3.11.2"})
    snaps = {"human": snapshot_from_records("human", "bash", h),
             "plain": snapshot_from_records("plain", "bash", a)}
    return snaps


SCRIPTED_BASHRC = BASHRC.replace("@@LOCALE@@", "C.UTF-8").splitlines()


def run_scripted() -> Dict[str, Any]:
    from .advise import RcFile, find_guard

    snaps = scripted_snapshots()
    rc = RcFile("/home/demo/.bashrc", "~/.bashrc", SCRIPTED_BASHRC, find_guard(SCRIPTED_BASHRC))
    res = analyze_snapshots(snaps, "bash", "/usr/bin/bash", "plain", "/home/demo",
                            rc_files=[rc])
    # Fixed answers so the output never depends on the machine running the demo.
    exists = {"/etc/profile": True, "~/.bash_profile": True, "~/.bashrc": True}
    for row in res["startup"]:
        if row["file"] != "$BASH_ENV":
            row["exists"] = exists.get(row["file"], False)
    res["demo"] = "scripted"
    return res


def run_demo(kind: str = "auto", shell_path: Optional[str] = None,
             timeout: float = 30.0) -> Dict[str, Any]:
    """kind: 'live', 'scripted' or 'auto' (live when bash is present)."""
    bash = shell_path or shutil.which("bash")
    if kind == "scripted" or (kind == "auto" and (not bash or sys.platform == "win32")):
        return run_scripted()
    if not bash:
        raise RuntimeError("the live demo needs bash; use --demo scripted")
    res, _ = run_live(bash, timeout)
    if not res["modes"]["human"]["ok"] and kind == "auto":
        return run_scripted()
    return res
