"""Pure comparison logic: two snapshots in, ranked findings out.

Nothing here spawns processes or touches the filesystem, so every rule can be
unit-tested with hand-written snapshots.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .probe import PROXY_VARS, RUNTIME_VARS
from .project import satisfies
from .snapshot import interesting_env_names, is_secret_name

SEVERITIES = ("error", "warn", "info")
SEV_RANK = {"error": 3, "warn": 2, "info": 1}

COVERED_VARS = set(PROXY_VARS) | {"LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "LC_MESSAGES",
                                  "SSH_AUTH_SOCK", "GPG_TTY", "TERM", "COLUMNS", "LINES"}


@dataclass
class Finding:
    id: str
    severity: str
    area: str
    title: str
    human: str = ""
    agent: str = ""
    detail: str = ""
    # Strings to look for in rc files (variable names, directories, manager markers).
    terms: List[str] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)
    # Filled in by advise():
    fix: List[str] = field(default_factory=list)
    where: List[str] = field(default_factory=list)
    visible_in: List[str] = field(default_factory=list)
    # Used only to compute visible_in; not serialised.
    present: Optional[Callable[[Dict[str, Any]], bool]] = field(default=None, repr=False,
                                                                compare=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "severity": self.severity, "area": self.area,
            "title": self.title, "human": self.human, "agent": self.agent,
            "detail": self.detail, "fix": self.fix, "where": self.where,
            "visible_in_modes": self.visible_in, "data": self.data,
        }


def norm_dir(p: str) -> str:
    return p.rstrip("/") or "/"


def _major(v: Optional[str]) -> Optional[int]:
    try:
        return int(v.split(".")[0]) if v else None
    except ValueError:
        return None


def _short(s: str, n: int = 70) -> str:
    return s if len(s) <= n else s[: n - 1] + "\u2026"


# --------------------------------------------------------------------- PATH

def _relevant(missing: List[str], human: Dict[str, Any]) -> List[str]:
    """Entries a startup file could have added: those under HOME, else all of them.
    (System directories often come from /etc/profile, which not every mode reads.)"""
    home = (human["vars"].get("HOME") or "").rstrip("/")
    under = [m for m in missing if home and m.startswith(home + "/")]
    return under or list(missing)


def compare_path(h: Dict[str, Any], a: Dict[str, Any]) -> List[Finding]:
    out: List[Finding] = []
    hp = [norm_dir(p) for p in h["path"]]
    ap = [norm_dir(p) for p in a["path"]]
    missing = [p for p in dict.fromkeys(hp) if p not in ap]
    if missing:
        shown = ", ".join(missing[:6]) + (" (+%d more)" % (len(missing) - 6)
                                          if len(missing) > 6 else "")
        out.append(Finding(
            id="path.missing", severity="warn", area="PATH",
            title="%d PATH director%s only in the human shell" % (
                len(missing), "y is" if len(missing) == 1 else "ies are"),
            human="%d entries" % len(hp), agent="%d entries" % len(ap),
            detail="Missing for the agent: " + shown,
            terms=list(missing), data={"missing": missing},
            present=lambda s, m=_relevant(missing, h): all(
                x in [norm_dir(p) for p in s["path"]] for x in m)))
    only_agent = [p for p in dict.fromkeys(ap) if p not in hp]
    if only_agent:
        out.append(Finding(
            id="path.agent_only", severity="info", area="PATH",
            title="%d PATH director%s only in the agent shell" % (
                len(only_agent), "y is" if len(only_agent) == 1 else "ies are"),
            detail=", ".join(only_agent[:6]), data={"extra": only_agent}))
    return out


# -------------------------------------------------------------------- tools

_MAJOR_SENSITIVE = {"node", "python", "python3", "go", "java", "rustc", "npm", "pnpm"}


def compare_tools(h: Dict[str, Any], a: Dict[str, Any]) -> List[Finding]:
    out: List[Finding] = []
    names = list(dict.fromkeys(list(h["tools"]) + list(a["tools"])))
    missing_by_dir: Dict[str, List[str]] = {}
    for name in names:
        ht, at = h["tools"].get(name), a["tools"].get(name)
        if ht and not at:
            if ht["kind"] == "path":
                missing_by_dir.setdefault(os.path.dirname(ht["where"]), []).append(name)
                continue
            out.append(Finding(
                id="tool.alias_only:%s" % name, severity="warn", area="tool",
                title="`%s` is an alias/function in the human shell only" % name,
                human=_short(ht["where"]), agent="command not found",
                detail="Aliases and functions defined in interactive rc files do "
                       "not exist for agents.",
                terms=[name], data={"tool": name},
                present=lambda s, n=name: n in s["tools"]))
            continue
        if at and not ht:
            out.append(Finding(
                id="tool.agent_only:%s" % name, severity="info", area="tool",
                title="`%s` exists only in the agent shell" % name,
                agent="%s (%s)" % (at["where"], at["version"] or "?"), data={"tool": name}))
            continue
        if not (ht and at):
            continue
        if ht["kind"] != "path" and at["kind"] == "path":
            out.append(Finding(
                id="tool.alias_shadow:%s" % name, severity="warn", area="tool",
                title="`%s` is an alias/function for you but a real binary for the agent" % name,
                human=_short(ht["where"]), agent=at["where"],
                detail="You and the agent may not run the same program.",
                terms=[name], data={"tool": name}))
            continue
        if ht["kind"] != "path" or at["kind"] != "path":
            continue
        h_fail = ht["rc"] not in (0, None)
        a_fail = at["rc"] not in (0, None)
        if a_fail and not h_fail:
            out.append(Finding(
                id="tool.broken:%s" % name, severity="error", area="tool",
                title="`%s` is found but fails to run in the agent shell" % name,
                human="%s (%s)" % (ht["where"], ht["version"] or "ok"),
                agent="%s -> exit %s: %s" % (at["where"], at["rc"], _short(at["raw"], 80)),
                detail="Found on PATH, but `--version` exits with an error (shown above). "
                       "Common causes: a version-manager shim with no version selected, or "
                       "a runtime it needs (node, python) that is missing from the agent's PATH.",
                terms=[name], data={"tool": name, "human_path": ht["where"]},
                present=lambda s, n=name, w=ht["where"]: s["tools"].get(n, {}).get("where") == w))
            continue
        if h_fail:
            continue
        hv, av = ht["version"], at["version"]
        same_path = ht["where"] == at["where"]
        if hv and av and hv != av:
            major_differs = _major(hv) != _major(av)
            sev = "error" if (major_differs and name in _MAJOR_SENSITIVE) else "warn"
            out.append(Finding(
                id="tool.version:%s" % name, severity=sev, area="tool",
                title="`%s` resolves to a different version for the agent" % name,
                human="%s  v%s" % (ht["where"], hv), agent="%s  v%s" % (at["where"], av),
                detail=("Same binary path, different result: an environment variable "
                        "(e.g. PYENV_VERSION, VOLTA_*, ASDF_*) differs." if same_path else
                        "Different binary first on PATH."),
                terms=[name], data={"tool": name, "human_path": ht["where"],
                                    "same_path": same_path},
                present=lambda s, n=name, v=hv: s["tools"].get(n, {}).get("version") == v))
        elif not same_path:
            out.append(Finding(
                id="tool.path:%s" % name, severity="info", area="tool",
                title="`%s` is the same version but a different binary" % name,
                human=ht["where"], agent=at["where"], terms=[name],
                data={"tool": name, "human_path": ht["where"]},
                present=lambda s, n=name, w=ht["where"]: s["tools"].get(n, {}).get("where") == w))
    for d, tools in missing_by_dir.items():
        first = tools[0]
        ht = h["tools"][first]
        names_txt = ", ".join("`%s`" % t for t in tools)
        out.append(Finding(
            id="tool.missing:%s" % first, severity="error", area="tool",
            title="%s %s not found in the agent shell" % (
                names_txt, "is" if len(tools) == 1 else "are"),
            human="%s (%s)" % (ht["where"], ht["version"] or "version unknown"),
            agent="command not found",
            detail="`command -v %s` finds %s in your terminal only%s." % (
                first, "it" if len(tools) == 1 else "them",
                "" if len(tools) == 1 else " (all in %s)" % d),
            terms=list(tools), data={"tool": first, "tools": list(tools),
                                     "human_path": ht["where"], "dir": d},
            present=lambda s, n=first: n in s["tools"]))
    return out


def _tool_version(snap: Dict[str, Any], tool: str) -> Optional[str]:
    names = ("python3", "python") if tool == "python" else (tool,)
    for n in names:
        t = snap["tools"].get(n)
        if t and t["kind"] == "path" and t["version"]:
            return t["version"]
    return None


def compare_project(h: Dict[str, Any], a: Dict[str, Any],
                    reqs: List[Dict[str, str]]) -> List[Finding]:
    out: List[Finding] = []
    for r in reqs:
        depth = 2 if r["tool"] == "python" else 1
        av, hv = _tool_version(a, r["tool"]), _tool_version(h, r["tool"])
        if av is None:
            continue
        a_ok = satisfies(av, r["spec"], depth)
        if a_ok is not False:
            continue
        h_ok = satisfies(hv, r["spec"], depth) if hv else None
        sev = "error" if h_ok else "warn"
        out.append(Finding(
            id="project.%s" % r["tool"], severity=sev, area="project",
            title="agent %s v%s does not satisfy this project (%s)" % (r["tool"], av, r["spec"]),
            human="v%s%s" % (hv, " (ok)" if h_ok else "") if hv else "not found",
            agent="v%s" % av,
            detail="Required by %s (checked at %s precision only)." % (
                r["source"], "major.minor" if depth == 2 else "major"),
            terms=[r["tool"]],
            data={"tool": r["tool"], "spec": r["spec"], "source": r["source"]},
            present=lambda s, t=r["tool"], sp=r["spec"], d=depth: bool(
                _tool_version(s, t) and satisfies(_tool_version(s, t), sp, d))))
    return out


# -------------------------------------------------------------------- proxy

def compare_proxy(h: Dict[str, Any], a: Dict[str, Any]) -> List[Finding]:
    out: List[Finding] = []
    hv, av = h["vars"], a["vars"]
    diff_only: List[str] = []
    diff_val: List[str] = []
    for n in PROXY_VARS:
        if n in hv and n not in av:
            diff_only.append(n)
        elif n in hv and n in av and hv[n] != av[n]:
            diff_val.append(n)
    if diff_only:
        out.append(Finding(
            id="proxy.missing", severity="warn", area="proxy",
            title="proxy variables set only in the human shell: %s" % ", ".join(diff_only),
            human="; ".join("%s=%s" % (n, hv[n]) for n in diff_only[:4]),
            agent="not set",
            detail="Network tools run by the agent connect directly (or time out) "
                   "instead of using your proxy.",
            terms=list(diff_only), data={"vars": diff_only, "values": {n: hv[n] for n in diff_only}},
            present=lambda s, ns=diff_only, v=hv: all(s["vars"].get(n) == v[n] for n in ns)))
    if diff_val:
        out.append(Finding(
            id="proxy.differs", severity="warn", area="proxy",
            title="proxy variables have different values: %s" % ", ".join(diff_val),
            human="; ".join("%s=%s" % (n, hv[n]) for n in diff_val[:3]),
            agent="; ".join("%s=%s" % (n, av[n]) for n in diff_val[:3]),
            terms=list(diff_val), data={"vars": diff_val, "values": {n: hv[n] for n in diff_val}},
            present=lambda s, ns=diff_val, v=hv: all(s["vars"].get(n) == v[n] for n in ns)))
    for label, snap in (("human", h), ("agent", a)):
        v = snap["vars"]
        for base in ("http_proxy", "https_proxy", "all_proxy"):
            lo, up = v.get(base), v.get(base.upper())
            if (lo is None) != (up is None):
                only = base if lo is not None else base.upper()
                miss = base.upper() if lo is not None else base
                out.append(Finding(
                    id="proxy.case:%s:%s" % (label, base), severity="info", area="proxy",
                    title="only `%s` is set in the %s shell (not `%s`)" % (only, label, miss),
                    detail="Tools disagree on which spelling they read (curl, for example, "
                           "honours lowercase http_proxy only). Setting both is safest.",
                    terms=[only], data={"shell": label, "set": only, "unset": miss,
                                        "value": v.get(only)}))
        if any(n in v for n in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")):
            npv = (v.get("no_proxy") or v.get("NO_PROXY") or "")
            if "localhost" not in npv and "127.0.0.1" not in npv:
                out.append(Finding(
                    id="proxy.no_proxy:%s" % label, severity="info", area="proxy",
                    title="proxy is set in the %s shell but NO_PROXY lacks localhost" % label,
                    detail="Requests to localhost/127.0.0.1 (dev servers, test runners) "
                           "may be sent through the proxy.",
                    terms=["no_proxy", "NO_PROXY"], data={"shell": label}))
    return out


# ------------------------------------------------------------------- locale

def compare_locale(h: Dict[str, Any], a: Dict[str, Any]) -> List[Finding]:
    out: List[Finding] = []
    hu, au = h["locale"]["utf8"], a["locale"]["utf8"]

    def desc(s: Dict[str, Any]) -> str:
        v = s["vars"]
        parts = ["%s=%s" % (n, v[n]) for n in ("LC_ALL", "LC_CTYPE", "LANG") if n in v]
        cm = s["locale"]["charmap"]
        u = s["locale"]["utf8"]
        tag = "UTF-8 ok" if u else ("NOT UTF-8" if u is False else "unknown")
        return "%s; charmap=%s; %s" % (", ".join(parts) or "no LANG/LC_*",
                                       cm or "?", tag)

    if au is False:
        sev = "error" if hu else "warn"
        why = ("Non-ASCII text (Persian, emoji, accents) in file names, git output and "
               "tool output can be mangled or fail with encoding errors.")
        detail = why
        v = a["vars"]
        if v.get("LC_ALL") and "utf" not in v["LC_ALL"].lower():
            detail += " LC_ALL=%s overrides LANG." % v["LC_ALL"]
        elif any("utf" in v.get(n, "").lower() for n in ("LANG", "LC_ALL", "LC_CTYPE")):
            detail += (" A UTF-8 locale name is set but the probe still counted bytes, so "
                       "that locale is probably not installed (see `locale -a`).")
        out.append(Finding(
            id="locale.agent_not_utf8", severity=sev, area="locale",
            title="the agent shell is not UTF-8" if hu else "neither shell is UTF-8",
            human=desc(h), agent=desc(a), detail=detail,
            terms=["LANG", "LC_ALL", "LC_CTYPE"], data={"human_utf8": hu},
            present=lambda s: s["locale"]["utf8"] is True))
    elif hu is False and au:
        out.append(Finding(
            id="locale.human_not_utf8", severity="info", area="locale",
            title="your terminal shell is not UTF-8 (the agent's is)",
            human=desc(h), agent=desc(a)))
    return out


# ---------------------------------------------------------------------- ssh

def compare_ssh(h: Dict[str, Any], a: Dict[str, Any]) -> List[Finding]:
    hs, as_ = h["vars"].get("SSH_AUTH_SOCK"), a["vars"].get("SSH_AUTH_SOCK")
    if hs and h["ssh_sock_ok"] and not (as_ and a["ssh_sock_ok"]):
        return [Finding(
            id="ssh.agent_missing", severity="warn", area="ssh",
            title="SSH_AUTH_SOCK is missing in the agent shell",
            human=hs, agent=("%s (not a socket)" % as_) if as_ else "not set",
            detail="git/ssh over SSH cannot use your keys; it fails or waits for a "
                   "passphrase that nobody can type.",
            terms=["SSH_AUTH_SOCK", "ssh-agent", "keychain"],
            data={"human_value": hs},
            present=lambda s: bool(s["vars"].get("SSH_AUTH_SOCK") and s["ssh_sock_ok"]))]
    if hs and not h["ssh_sock_ok"]:
        return [Finding(
            id="ssh.human_stale", severity="info", area="ssh",
            title="SSH_AUTH_SOCK points to a path that is not a socket (human shell)",
            human=hs, detail="A stale agent socket; nothing for the agent to inherit.")]
    return []


# ---------------------------------------------------------------------- git

def compare_git(h: Dict[str, Any], a: Dict[str, Any]) -> List[Finding]:
    out: List[Finding] = []
    hg, ag = h["git"], a["git"]
    for key in sorted(set(hg) | set(ag)):
        hv, av = hg.get(key), ag.get(key)
        if hv == av:
            continue
        sev = "warn" if key in ("user.name", "user.email", "credential.helper",
                                "user.signingkey", "commit.gpgsign") else "info"
        out.append(Finding(
            id="git.config:%s" % key, severity=sev, area="git",
            title="git `%s` differs" % key,
            human=hv if hv is not None else "unset", agent=av if av is not None else "unset",
            detail="Git reads config relative to HOME / XDG_CONFIG_HOME / GIT_CONFIG_GLOBAL, "
                   "so one of those differs between the two shells.",
            terms=["GIT_CONFIG_GLOBAL", "XDG_CONFIG_HOME", "HOME"], data={"key": key}))
    signs = ag.get("commit.gpgsign", "").lower() == "true"
    fmt = ag.get("gpg.format", "openpgp")
    if signs and fmt != "ssh" and "GPG_TTY" not in a["vars"] and not a["tty"]["stdin"]:
        out.append(Finding(
            id="git.gpg_tty", severity="warn", area="git",
            title="git commit signing is on, but the agent shell has no TTY and no GPG_TTY",
            human="GPG_TTY=%s" % h["vars"].get("GPG_TTY", "unset"),
            agent="GPG_TTY unset, stdin is not a tty",
            detail="gpg's pinentry cannot ask for the passphrase, so `git commit` can fail "
                   "with 'gpg failed to sign the data' unless gpg-agent already has it cached.",
            terms=["GPG_TTY"], data={}))
    if signs and fmt == "ssh" and not (a["vars"].get("SSH_AUTH_SOCK") and a["ssh_sock_ok"]):
        out.append(Finding(
            id="git.ssh_signing", severity="warn", area="git",
            title="git signs commits with SSH, but the agent shell has no SSH agent",
            agent="SSH_AUTH_SOCK missing", terms=["SSH_AUTH_SOCK"], data={},
            detail="Signing needs the key (or an agent holding it); an encrypted key "
                   "file cannot prompt for its passphrase."))
    return out


# ------------------------------------------------------- tty / env / misc

def compare_tty(h: Dict[str, Any], a: Dict[str, Any]) -> List[Finding]:
    out: List[Finding] = []
    if h["tty"]["stdin"] and not a["tty"]["stdin"]:
        out.append(Finding(
            id="tty.stdin", severity="info", area="tty",
            title="stdin is a TTY in the human shell but not in the agent shell",
            human="tty", agent="no tty",
            detail="Expected for agents. Commands that prompt (git credentials, ssh, sudo, "
                   "installers) cannot be answered; pass non-interactive flags."))
    t = a["vars"].get("TERM")
    if h["vars"].get("TERM") and (not t or t == "dumb"):
        out.append(Finding(
            id="tty.term", severity="info", area="tty",
            title="TERM is %s in the agent shell" % ("unset" if not t else "'dumb'"),
            human="TERM=%s" % h["vars"]["TERM"], agent="TERM=%s" % (t or "unset"),
            detail="Colour, `tput`, `less` and some CLIs behave differently without a terminal type."))
    return out


def compare_env(h: Dict[str, Any], a: Dict[str, Any]) -> List[Finding]:
    out: List[Finding] = []
    hv, av = h["vars"], a["vars"]
    skip = COVERED_VARS | {"SHELL", "HOME", "USER", "LOGNAME"}
    rt = set(RUNTIME_VARS)
    for n in sorted(set(hv) | set(av)):
        if n in skip:
            continue
        if n in hv and n not in av:
            sev = "warn" if n in rt else "info"
            out.append(Finding(
                id="env.missing:%s" % n, severity=sev, area="env",
                title="`%s` is set only in the human shell" % n,
                human=_short(hv[n]), agent="not set", terms=[n],
                data={"var": n, "value": hv[n]},
                present=lambda s, n=n, v=hv[n]: s["vars"].get(n) == v))
        elif n in hv and n in av and hv[n] != av[n]:
            sev = "warn" if n in rt else "info"
            out.append(Finding(
                id="env.differs:%s" % n, severity=sev, area="env",
                title="`%s` differs between the shells" % n,
                human=_short(hv[n]), agent=_short(av[n]), terms=[n],
                data={"var": n, "value": hv[n]},
                present=lambda s, n=n, v=hv[n]: s["vars"].get(n) == v))
        elif n in av and n not in hv and n in rt:
            out.append(Finding(
                id="env.agent_only:%s" % n, severity="info", area="env",
                title="`%s` is set only in the agent shell" % n,
                agent=_short(av[n]), data={"var": n}))
    hn = set(interesting_env_names(h["env_names"]))
    an = set(a["env_names"])
    secrets = sorted(n for n in hn if n not in an and is_secret_name(n))
    if secrets:
        out.append(Finding(
            id="env.secrets_missing", severity="warn", area="env",
            title="%d secret-looking variable%s exist only in the human shell" % (
                len(secrets), " does" if len(secrets) == 1 else "s"),
            human=", ".join(secrets[:12]) + (" ..." if len(secrets) > 12 else ""),
            agent="not set",
            detail="Only the names are compared; values are never read or stored. "
                   "Agents cannot call APIs that need these keys.",
            terms=secrets, data={"names": secrets},
            present=lambda s, ns=secrets: all(n in s["env_names"] for n in ns)))
    others = sorted(n for n in hn if n not in an and not is_secret_name(n)
                    and n not in set(hv) and n not in COVERED_VARS)
    if others:
        out.append(Finding(
            id="env.others_missing", severity="info", area="env",
            title="%d other exported variable%s exist only in the human shell" % (
                len(others), " exists" if len(others) == 1 else "s"),
            human=", ".join(others[:15]) + (" ..." if len(others) > 15 else ""),
            terms=others[:15], data={"names": others}))
    return out


def compare_misc(h: Dict[str, Any], a: Dict[str, Any]) -> List[Finding]:
    out: List[Finding] = []
    if h["aliases"] and not a["aliases"]:
        out.append(Finding(
            id="misc.aliases", severity="info", area="shell",
            title="%d alias%s in the human shell, none in the agent shell" % (
                h["aliases"], " exists" if h["aliases"] == 1 else "es exist"),
            detail="Aliases like `ll`, `gs` or `python=python3` do not work for agents; "
                   "use real commands or scripts on PATH."))
    for key, label in (("umask", "umask"), ("ulimit_n", "open-files limit (ulimit -n)"),
                       ("tz_abbr", "timezone abbreviation")):
        if h[key] and a[key] and h[key] != a[key]:
            out.append(Finding(
                id="misc.%s" % key, severity="info", area="shell",
                title="%s differs" % label, human=h[key], agent=a[key]))
    if not h["interactive"]:
        out.append(Finding(
            id="probe.human_not_interactive", severity="warn", area="probe",
            title="the 'human' probe did not run as an interactive shell",
            detail="flags=%r. Interactive rc files may not have been read, so results can "
                   "understate your terminal." % h["flags"]))
    return out


# --------------------------------------------------------------------- main

def compare(human: Dict[str, Any], agent: Dict[str, Any],
            requirements: Optional[List[Dict[str, str]]] = None) -> List[Finding]:
    """Diff the human snapshot against the agent snapshot; most severe first."""
    findings: List[Finding] = []
    findings += compare_tools(human, agent)
    findings += compare_project(human, agent, requirements or [])
    findings += compare_path(human, agent)
    findings += compare_proxy(human, agent)
    findings += compare_locale(human, agent)
    findings += compare_ssh(human, agent)
    findings += compare_git(human, agent)
    findings += compare_env(human, agent)
    findings += compare_tty(human, agent)
    findings += compare_misc(human, agent)
    order = {f.id: i for i, f in enumerate(findings)}
    findings.sort(key=lambda f: (-SEV_RANK[f.severity], order[f.id]))
    return findings


def summarize(findings: List[Finding]) -> Dict[str, int]:
    return {s: sum(1 for f in findings if f.severity == s) for s in SEVERITIES}
