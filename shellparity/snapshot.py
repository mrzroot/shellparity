"""Turn raw probe records into a normalised, secret-safe snapshot dict."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

SECRET_NAME_RE = re.compile(
    r"(TOKEN|SECRET|PASSWORD|PASSWD|API_?KEY|APIKEY|ACCESS_?KEY|PRIVATE_?KEY|"
    r"CREDENTIALS?|_PAT$|_KEY$|^PGPASSWORD$)", re.I)
URL_CRED_RE = re.compile(r"(://)([^/\s:@]+):([^/\s@]+)@")
URL_USER_RE = re.compile(r"(://)([^/\s:@]+)@")

# Variables that exist in nearly every shell or change on every run; they are
# not interesting in the "other variables only in the human shell" list.
NOISE_ENV = {
    "_", "SHLVL", "PWD", "OLDPWD", "SP_OUT", "LS_COLORS", "LESSOPEN", "LESSCLOSE",
    "LESS", "COLORTERM", "WINDOWID", "TERM_PROGRAM", "TERM_PROGRAM_VERSION",
    "TERM_SESSION_ID", "OLDPWD", "PS1", "PS2", "PROMPT_COMMAND", "INPUTRC",
    "HISTFILE", "HISTSIZE", "HISTFILESIZE", "HISTCONTROL", "MAIL", "MANPATH",
    "INFOPATH", "LANGUAGE", "LOGNAME", "USER", "HOME", "SHELL", "COLUMNS", "LINES",
    "ZDOTDIR", "KEYTIMEOUT", "WSLENV", "ITERM_SESSION_ID", "VTE_VERSION",
    "STARSHIP_SHELL", "STARSHIP_SESSION_KEY", "ZSH", "ZSH_CACHE_DIR", "ZSH_COMPDUMP",
}
NOISE_PREFIXES = ("XDG_", "DBUS_", "GNOME_", "KDE_", "WAYLAND_", "DISPLAY", "XAUTH",
                  "LESS", "LC_", "SP_", "BASH_FUNC_", "P9K_", "POWERLEVEL9K_",
                  "ITERM_", "VSCODE_", "COLORFGBG", "TERMINAL_", "MOTD_", "MAMBA_",
                  "CONDA_SHLVL", "CONDA_EXE", "_CE_", "_CONDA_")


def is_secret_name(name: str) -> bool:
    return bool(SECRET_NAME_RE.search(name))


def mask_value(name: str, value: str) -> str:
    """Mask credentials inside a value. Secret-looking names are never stored."""
    if is_secret_name(name):
        return "<set>"
    return mask_text(value)


def mask_text(value: str) -> str:
    value = URL_CRED_RE.sub(r"\1***:***@", value)
    return URL_USER_RE.sub(r"\1***@", value)


_ASSIGN_RE = re.compile(
    r"""([A-Za-z_][A-Za-z0-9_]*)=("(?:[^"\\]|\\.)*"|'[^']*'|\S+)""")


def redact_line(line: str) -> str:
    """Make a line of shell source safe to print: secret-named assignments lose their
    value and URL credentials are masked."""
    def repl(m: "re.Match[str]") -> str:
        if is_secret_name(m.group(1)):
            return "%s=<redacted>" % m.group(1)
        return m.group(0)
    return mask_text(_ASSIGN_RE.sub(repl, line))


def parse_records(text: str) -> Dict[str, str]:
    """Parse ``SP<TAB>key<TAB>value`` lines; unrelated lines are ignored."""
    rec: Dict[str, str] = {}
    for line in text.splitlines():
        if not line.startswith("SP\t"):
            continue
        parts = line.split("\t", 2)
        if len(parts) < 2:
            continue
        rec[parts[1]] = parts[2] if len(parts) == 3 else ""
    return rec


_VER_RE = re.compile(r"(\d+(?:\.\d+){1,3})")


def extract_version(raw: str) -> Optional[str]:
    m = _VER_RE.search(raw or "")
    return m.group(1) if m else None


def _truthy(v: Optional[str]) -> Optional[bool]:
    if v is None or v == "":
        return None
    return v == "1"


def snapshot_from_records(mode: str, shell: str, rec: Dict[str, str]) -> Dict[str, Any]:
    """Build the snapshot. Pure function, unit-tested with synthetic records."""
    tools: Dict[str, Dict[str, Any]] = {}
    for key, val in rec.items():
        if key.startswith("tool:") and key.endswith(":where"):
            name = key[len("tool:"):-len(":where")]
            where = val
            kind = "path" if where.startswith("/") else "other"
            raw = rec.get("tool:%s:ver" % name, "")
            rc_s = rec.get("tool:%s:rc" % name)
            tools[name] = {
                "kind": kind,
                "where": where,
                "rc": int(rc_s) if (rc_s or "").lstrip("-").isdigit() else None,
                "raw": mask_text(raw)[:200],
                "version": extract_version(raw) if kind == "path" else None,
            }
    env_names = [n for n in rec.get("envnames", "").split() if n]
    exported = set(env_names)
    variables: Dict[str, str] = {}
    for key, val in rec.items():
        if key.startswith("var:"):
            name = key[4:]
            if name == "PATH" or name in exported or name in ("COLUMNS", "LINES"):
                variables[name] = mask_value(name, val)
    # COLUMNS/LINES are shell-managed and normally not exported; keep as hints only.
    flags = rec.get("flags", "")
    chars: Optional[int] = None
    pc = rec.get("persian_chars", "")
    if pc.isdigit():
        chars = int(pc)
    utf8: Optional[bool] = None
    if chars == 4:
        utf8 = True
    elif chars == 8:
        utf8 = False
    git = {k[4:]: mask_text(v) for k, v in rec.items() if k.startswith("git:")}
    snap: Dict[str, Any] = {
        "mode": mode,
        "shell": shell,
        "ok": rec.get("done") == "1",
        "error": None,
        "shell_version": rec.get("shellver", ""),
        "flags": flags,
        "interactive": "i" in flags,
        "path": [p for p in rec.get("path", "").split(":") if p],
        "tools": tools,
        "vars": variables,
        "env_names": env_names,
        "tty": {"stdin": _truthy(rec.get("tty0")), "stdout": _truthy(rec.get("tty1")),
                "stderr": _truthy(rec.get("tty2"))},
        "locale": {"charmap": rec.get("charmap", ""), "persian_chars": chars,
                   "utf8": utf8},
        "git": git,
        "ssh_sock_ok": _truthy(rec.get("ssh_sock_ok")),
        "aliases": int(rec["aliases"]) if rec.get("aliases", "").isdigit() else None,
        "umask": rec.get("umask", ""),
        "ulimit_n": rec.get("ulimit_n", ""),
        "tz_abbr": rec.get("tz_abbr", ""),
    }
    return snap


def failed_snapshot(mode: str, shell: str, error: str) -> Dict[str, Any]:
    snap = snapshot_from_records(mode, shell, {})
    snap["ok"] = False
    snap["error"] = error
    return snap


def interesting_env_names(names: List[str]) -> List[str]:
    out = []
    for n in names:
        if n in NOISE_ENV or n.startswith(NOISE_PREFIXES):
            continue
        out.append(n)
    return out
