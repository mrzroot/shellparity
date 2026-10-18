"""Startup-file knowledge and the 'exact fix' text.

Everything here is read-only: it reads (never writes) the user's rc files to
tell them *where* a definition lives. Fixes are printed, never applied.
"""

from __future__ import annotations

import os
import re
import shlex
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .compare import Finding
from .snapshot import mask_text, redact_line

# Which modes read which files (documented behaviour of each shell).
STARTUP_FILES: Dict[str, List[Tuple[str, List[str], str]]] = {
    "bash": [
        ("/etc/profile", ["human", "login"], "login shells"),
        ("~/.bash_profile", ["human", "login"], "login shells (first of the three that exists)"),
        ("~/.bash_login", ["human", "login"], "login shells (only if no ~/.bash_profile)"),
        ("~/.profile", ["human", "login"], "login shells (only if no ~/.bash_profile or ~/.bash_login)"),
        ("~/.bashrc", ["interactive"], "interactive non-login shells; login shells only if a profile file sources it"),
        ("$BASH_ENV", ["plain", "login", "interactive"], "non-interactive shells, only if BASH_ENV is set"),
    ],
    "zsh": [
        ("~/.zshenv", ["human", "login", "interactive", "plain"], "every zsh, including `zsh -c`"),
        ("~/.zprofile", ["human", "login"], "login shells"),
        ("~/.zshrc", ["human", "interactive"], "interactive shells"),
        ("~/.zlogin", ["human", "login"], "login shells (after .zshrc)"),
    ],
    "sh": [
        ("/etc/profile", ["human", "login"], "login shells"),
        ("~/.profile", ["human", "login"], "login shells"),
        ("$ENV", ["human", "interactive"], "interactive shells, only if ENV is set"),
    ],
}

USER_RC: Dict[str, List[str]] = {
    "bash": ["~/.bash_profile", "~/.bash_login", "~/.profile", "~/.bashrc"],
    "zsh": ["~/.zshenv", "~/.zprofile", "~/.zshrc", "~/.zlogin"],
    "sh": ["~/.profile"],
}

GUARD_RES = [
    re.compile(r"^\s*\[\[?\s*\$-\s*!=\s*\*i\*\s*\]\]?\s*&&\s*(return|exit)"),
    re.compile(r"^\s*\[\[?\s*\$-\s*==\s*\*i\*\s*\]\]?\s*\|\|\s*(return|exit)"),
    re.compile(r"^\s*\[\s+-z\s+\"?\$PS1\"?\s+\]\s*&&\s*(return|exit)"),
    re.compile(r"^\s*\[\[\s+-z\s+\"?\$PS1\"?\s+\]\]\s*&&\s*(return|exit)"),
    re.compile(r"^\s*\[\[?\s*-o\s+interactive\s*\]\]?\s*\|\|\s*(return|exit)"),
    re.compile(r"^\s*\[\s+-n\s+\"?\$PS1\"?\s+\]\s*\|\|\s*(return|exit)"),
]
CASE_START_RE = re.compile(r"^\s*case\s+\$-\s+in\b")
CASE_RETURN_RE = re.compile(r"\*\)\s*(return|exit)\b")

MARKERS = [
    ("nvm", re.compile(r"nvm\.sh|NVM_DIR")),
    ("pyenv", re.compile(r"pyenv\s+init|PYENV_ROOT")),
    ("fnm", re.compile(r"fnm\s+env")),
    ("mise", re.compile(r"mise\s+activate|mise/shims")),
    ("asdf", re.compile(r"asdf\.sh|\.asdf")),
    ("volta", re.compile(r"VOLTA_HOME")),
    ("conda", re.compile(r"conda\s+initialize|conda\.sh")),
    ("sdkman", re.compile(r"sdkman-init")),
    ("rbenv", re.compile(r"rbenv\s+init")),
    ("ssh-agent", re.compile(r"ssh-agent|keychain|SSH_AUTH_SOCK")),
    ("gpg", re.compile(r"GPG_TTY")),
]

SOURCE_RE = re.compile(r"^\s*(?:source|\.)\s+([\"']?)([^\s\"';&|]+)\1")


@dataclass
class RcFile:
    path: str            # absolute
    display: str         # ~-relative
    lines: List[str]
    guard_line: Optional[int] = None
    sourced_from: Optional[str] = None


@dataclass
class AdviceContext:
    shell: str
    home: str
    agent_mode: str
    snaps: Dict[str, Dict[str, Any]]
    platform: str = sys.platform
    files: List[RcFile] = field(default_factory=list)


def tilde(path: str, home: str) -> str:
    home = home.rstrip("/")
    if home and (path == home or path.startswith(home + "/")):
        return "~" + path[len(home):]
    return path


def home_var(path: str, home: str) -> str:
    """Rewrite an absolute path to use $HOME so a suggested line is portable."""
    home = home.rstrip("/")
    if home and (path == home or path.startswith(home + "/")):
        return "$HOME" + path[len(home):]
    return path


def _expand(token: str, home: str) -> str:
    token = token.replace("${HOME}", home).replace("$HOME", home)
    if token.startswith("~/"):
        token = home + token[1:]
    return token


def find_guard(lines: List[str]) -> Optional[int]:
    """1-based line number of an interactive-only early return, if any."""
    for i, raw in enumerate(lines):
        if raw.lstrip().startswith("#"):
            continue
        if any(r.search(raw) for r in GUARD_RES):
            return i + 1
        if CASE_START_RE.search(raw):
            for j in range(i + 1, min(i + 6, len(lines))):
                if CASE_RETURN_RE.search(lines[j]):
                    return i + 1
    return None


def _read_lines(path: str) -> Optional[List[str]]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read().splitlines()
    except OSError:
        return None


def scan_rc_files(shell: str, home: str) -> List[RcFile]:
    """Read the user's startup files (and files they source, two levels deep)."""
    out: List[RcFile] = []
    seen = set()

    def add(path: str, via: Optional[str], depth: int) -> None:
        path = os.path.normpath(path)
        if path in seen or depth > 2:
            return
        lines = _read_lines(path)
        if lines is None:
            return
        seen.add(path)
        rf = RcFile(path, tilde(path, home), lines, find_guard(lines), via)
        out.append(rf)
        for raw in lines:
            if raw.lstrip().startswith("#"):
                continue
            m = SOURCE_RE.match(raw)
            if m:
                target = _expand(m.group(2), home)
                if os.path.isabs(target) and "$" not in target and not target.startswith("/etc/"):
                    add(target, rf.display, depth + 1)

    for rc in USER_RC.get(shell, []):
        add(_expand(rc, home), None, 0)
    return out


def _var_def_re(name: str) -> "re.Pattern[str]":
    return re.compile(r"(^|[\s;&(])(?:export\s+|typeset\s+-x\s+|declare\s+-x\s+|setenv\s+)?%s=" % re.escape(name))


def locate(f: Finding, ctx: AdviceContext) -> List[str]:
    """Find where the human-side definition lives. Textual search only."""
    hits: List[str] = []
    kind = f.id.split(":", 1)[0]
    patterns: List["re.Pattern[str]"] = []
    if kind in ("proxy.missing", "proxy.differs", "env.missing", "env.differs",
                "env.secrets_missing", "locale.agent_not_utf8", "ssh.agent_missing",
                "git.gpg_tty", "git.ssh_signing", "proxy.case"):
        names = list(f.terms)
        if kind == "locale.agent_not_utf8":
            names = ["LANG", "LC_ALL", "LC_CTYPE"]
        patterns = [_var_def_re(n) for n in names[:40]]
        if kind == "ssh.agent_missing":
            patterns.append(re.compile(r"ssh-agent|keychain"))
    elif kind == "path.missing":
        for entry in f.terms[:30]:
            for form in {entry, home_var(entry, ctx.home), tilde(entry, ctx.home),
                         home_var(entry, ctx.home).replace("$HOME", "${HOME}")}:
                patterns.append(re.compile(re.escape(form) + r"(?![\w.-])"))
    elif kind in ("tool.missing", "tool.broken", "tool.version", "tool.path"):
        d = f.data.get("dir") or os.path.dirname(f.data.get("human_path", ""))
        if d:
            for form in {d, home_var(d, ctx.home), tilde(d, ctx.home)}:
                patterns.append(re.compile(re.escape(form) + r"(?![\w.-])"))
        mgr = manager_for(f.data.get("human_path", ""))
        for name, rx in MARKERS:
            if name == mgr:
                patterns.append(rx)
    for rf in ctx.files:
        for i, raw in enumerate(rf.lines):
            if raw.lstrip().startswith("#"):
                continue
            if any(p.search(raw) for p in patterns):
                text = redact_line(raw.strip())
                if len(text) > 90:
                    text = text[:89] + "\u2026"
                note = ""
                if rf.guard_line and i + 1 > rf.guard_line:
                    note = "  (below the interactive-only guard at line %d)" % rf.guard_line
                hits.append("%s:%d: %s%s" % (rf.display, i + 1, text, note))
                if len(hits) >= 5:
                    return hits
    return hits


def manager_for(path: str) -> str:
    p = path or ""
    table = [
        ("/.nvm/", "nvm"), ("/.pyenv/", "pyenv"), ("/.asdf/", "asdf"),
        ("/mise/", "mise"), ("/.volta/", "volta"), ("fnm_multishells", "fnm"),
        ("/.fnm/", "fnm"), ("conda", "conda"), ("/.cargo/", "cargo"),
        ("/.sdkman/", "sdkman"), ("/.rbenv/", "rbenv"),
        ("/opt/homebrew/", "brew"), ("/linuxbrew/", "brew"),
        ("/.local/share/pnpm", "pnpm"),
    ]
    for needle, name in table:
        if needle in p:
            return name
    return ""


def manager_lines(mgr: str, human_path: str, ctx: AdviceContext) -> List[str]:
    d = os.path.dirname(human_path)
    pin = 'export PATH="%s:$PATH"' % home_var(d, ctx.home)
    if mgr == "pyenv":
        return ['export PYENV_ROOT="$HOME/.pyenv"',
                'export PATH="$PYENV_ROOT/shims:$PYENV_ROOT/bin:$PATH"']
    if mgr == "asdf":
        return ['export PATH="${ASDF_DATA_DIR:-$HOME/.asdf}/shims:$PATH"']
    if mgr == "mise":
        return [pin]
    if mgr == "volta":
        return ['export VOLTA_HOME="$HOME/.volta"', 'export PATH="$VOLTA_HOME/bin:$PATH"']
    if mgr == "fnm":
        return ['eval "$(fnm env)"']
    if mgr == "cargo":
        return ['. "$HOME/.cargo/env"']
    if mgr == "brew":
        brew = "/opt/homebrew/bin/brew" if "/opt/homebrew" in human_path else "/home/linuxbrew/.linuxbrew/bin/brew"
        return ['eval "$(%s shellenv)"' % brew]
    return [pin]


MANAGER_NOTE = {
    "nvm": "nvm is a shell function loaded from nvm.sh; agents never load it, so only the "
           "resolved bin directory can be pinned. Re-pin after `nvm use`/`nvm alias default`.",
    "pyenv": "pyenv shims work without `pyenv init` as long as the shims directory is on PATH. "
             "The selected version still comes from PYENV_VERSION or .python-version files.",
    "asdf": "asdf shims resolve versions from .tool-versions files, so the directory must "
            "match the project.",
    "conda": "`conda activate` is a shell function; pin the environment's bin directory instead.",
    "fnm": "fnm creates a per-shell directory; `fnm env` must run in the agent's shell.",
}


def target_for(ctx: AdviceContext) -> Tuple[str, str]:
    """(file shown to the user, one-line reason) for where agent-visible exports belong."""
    sh, mode = ctx.shell, ctx.agent_mode
    exists = lambda p: os.path.exists(_expand(p, ctx.home))  # noqa: E731
    if sh == "zsh":
        return "~/.zshenv", "zsh reads ~/.zshenv for every shell, including `zsh -c`"
    if sh == "bash":
        if mode == "login":
            first = next((p for p in ("~/.bash_profile", "~/.bash_login", "~/.profile")
                          if exists(p)), "~/.profile")
            return first, "login bash reads only the first of ~/.bash_profile, ~/.bash_login, ~/.profile"
        if mode == "interactive":
            return "~/.bashrc", "interactive bash reads ~/.bashrc"
        return "~/.bash_env", ("non-interactive bash reads nothing except the file named by "
                               "$BASH_ENV; set BASH_ENV=$HOME/.bash_env in the environment "
                               "that launches the agent")
    if mode == "login":
        return "~/.profile", "login sh reads ~/.profile"
    return "", ("POSIX sh reads no startup file for `sh -c`; export the line where the agent "
                "is launched (its settings or launcher), or run the agent with bash/zsh")


def _export(name: str, value: str, where: List[str]) -> List[str]:
    if "***" in value or value == "<set>":
        src = where[0].split(":", 2)[:2] if where else None
        hint = "copy the real line from %s" % (":".join(src) if src else "your rc file")
        return ["# %s contains credentials: %s" % (name, hint)]
    return ["export %s=%s" % (name, shlex.quote(value))]


def snippet_for(f: Finding, ctx: AdviceContext) -> List[str]:
    """Shell lines that would make the agent shell match, when we can state them."""
    kind = f.id.split(":", 1)[0]
    d = f.data
    if kind == "path.missing":
        entries = [home_var(p, ctx.home) for p in d["missing"]]
        return ['export PATH="%s:$PATH"' % ":".join(entries)]
    if kind in ("tool.missing", "tool.broken"):
        return manager_lines(manager_for(d.get("human_path", "")), d.get("human_path", ""), ctx)
    if kind == "tool.version":
        if d.get("same_path"):
            return []
        return manager_lines(manager_for(d.get("human_path", "")), d.get("human_path", ""), ctx)
    if kind in ("proxy.missing", "proxy.differs"):
        out: List[str] = []
        for n in d["vars"]:
            out += _export(n, d["values"][n], f.where)
        return out
    if kind in ("env.missing", "env.differs"):
        return _export(d["var"], d["value"], f.where)
    if kind == "locale.agent_not_utf8":
        hv = ctx.snaps.get("human", {}).get("vars", {})
        cand = next((hv[n] for n in ("LC_ALL", "LANG") if "utf" in hv.get(n, "").lower()), None)
        loc = cand or ("en_US.UTF-8" if ctx.platform == "darwin" else "C.UTF-8")
        lines = ["export LANG=%s" % loc]
        av = ctx.snaps.get(ctx.agent_mode, {}).get("vars", {})
        if av.get("LC_ALL"):
            lines.append("export LC_ALL=%s" % loc)
        return lines
    if kind == "ssh.agent_missing":
        return ['# only if the socket path is stable (systemd, gnome-keyring, launchd):',
                'export SSH_AUTH_SOCK=%s' % shlex.quote(d["human_value"])]
    return []


def _dest(ctx: AdviceContext) -> str:
    target, _ = target_for(ctx)
    return "Add to %s:" % target if target else "Export where the agent is launched:"


def placement(ctx: AdviceContext, findings: List[Finding]) -> Dict[str, Any]:
    """The one-time 'where do fixes go' explanation, plus shortcut counts."""
    target, reason = target_for(ctx)
    fixable = [f for f in findings if f.data.get("snippet") or f.fix]
    shortcuts: Dict[str, int] = {}
    for m in ("login", "interactive"):
        if m != ctx.agent_mode:
            n = sum(1 for f in findings if m in f.visible_in)
            if n:
                shortcuts[m] = n
    return {"target": target, "reason": reason, "shortcuts": shortcuts,
            "fixable": len(fixable)}


def advise(findings: List[Finding], ctx: AdviceContext) -> None:
    """Fill ``fix``, ``where`` and ``visible_in`` on each finding (in place)."""
    others = [m for m in ctx.snaps if m not in ("human", ctx.agent_mode)
              and ctx.snaps[m].get("ok")]
    seen_snip: Dict[tuple, int] = {}
    path_missing: set = set()
    for f in findings:
        if f.id == "path.missing":
            path_missing = set(f.data["missing"])
    for idx, f in enumerate(findings, 1):
        f.data["number"] = idx
        if f.present is not None:
            f.visible_in = [m for m in others if f.present(ctx.snaps[m])]
        if f.severity == "info" and f.id.split(":")[0] not in ("proxy.case",):
            continue
        f.where = locate(f, ctx)
        snippet = snippet_for(f, ctx)
        kind = f.id.split(":", 1)[0]
        fix: List[str] = []
        if kind == "env.secrets_missing":
            fix.append("Give these to the agent explicitly (its settings or a secrets manager), "
                       "or `export NAME=...` in the file named above. Never commit them.")
        elif kind == "git.gpg_tty":
            fix += ["Either let the agent commit unsigned: `git -c commit.gpgsign=false commit ...`,",
                    "or switch to SSH signing (`git config --global gpg.format ssh`) with an ssh-agent,",
                    "or pre-cache the passphrase in gpg-agent (gpg-preset-passphrase)."]
        elif kind == "git.ssh_signing":
            fix.append("Give the agent shell an ssh-agent holding the signing key (see the "
                       "SSH_AUTH_SOCK finding) or use a key without a passphrase.")
        elif kind == "git.config":
            fix.append("Check that HOME, XDG_CONFIG_HOME and GIT_CONFIG_GLOBAL are the same for "
                       "the agent; run `git config --show-origin --get %s` in both." % f.data["key"])
        elif kind in ("tool.alias_only", "tool.alias_shadow"):
            fix.append("Replace the alias with a real script on PATH (e.g. in ~/.local/bin) so "
                       "both shells run the same program.")
        elif kind in ("project.node", "project.python"):
            fix.append("Make the agent shell resolve a compatible %s: apply the `%s` fix above "
                       "or select the version the project asks for." % (f.data["tool"], f.data["tool"]))
        elif kind == "tool.version" and f.data.get("same_path"):
            fix.append("The binary is the same, so a version-selector variable differs. Compare "
                       "the env findings (PYENV_VERSION, ASDF_*, VOLTA_*) and export the same "
                       "value for the agent.")
        elif kind == "proxy.case":
            val = f.data.get("value") or ""
            if "***" not in val and val:
                fix.append("Also set the other spelling: export %s=%s"
                           % (f.data["unset"], shlex.quote(val)))
        elif (kind in ("tool.missing", "tool.broken") and snippet and
              not manager_for(f.data.get("human_path", "")) and
              os.path.dirname(f.data.get("human_path", "")) in path_missing):
            fix.append("Covered by the PATH fix (it adds %s)." % os.path.dirname(f.data["human_path"]))
            snippet = []
        elif snippet:
            key = tuple(snippet)
            if key in seen_snip:
                fix.append("Same lines as finding #%d." % seen_snip[key])
                snippet = []
            else:
                seen_snip[key] = idx
        if snippet and kind != "proxy.case":
            if kind in ("tool.missing", "tool.broken", "tool.version"):
                mgr = manager_for(f.data.get("human_path", ""))
                if mgr in MANAGER_NOTE:
                    fix.append(MANAGER_NOTE[mgr])
            fix.append(_dest(ctx))
            fix += ["    " + s for s in snippet]
            f.data["snippet"] = list(snippet)
        f.fix = fix


def startup_report(ctx: AdviceContext) -> List[Dict[str, Any]]:
    """Which startup files exist, who reads them, and any early-return guards."""
    rows: List[Dict[str, Any]] = []
    guards = {rf.display: rf.guard_line for rf in ctx.files}
    for raw, modes, note in STARTUP_FILES.get(ctx.shell, []):
        if raw.startswith("$"):
            exists: Optional[bool] = None
            real = ctx.snaps.get(ctx.agent_mode, {}).get("vars", {}).get(raw[1:])
            if real:
                exists = True
        else:
            exists = os.path.exists(_expand(raw, ctx.home))
        rows.append({"file": raw, "exists": exists, "read_by": modes, "note": note,
                     "guard_line": guards.get(raw)})
    return rows
