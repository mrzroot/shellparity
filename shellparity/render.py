"""Renderers: human text, Markdown and JSON."""

from __future__ import annotations

import json
import sys
import textwrap
from typing import Any, Dict, List, Optional

from . import __version__
from .advise import tilde
from .compare import Finding, summarize
from .runner import MODE_HELP

RESET = "\033[0m"
STYLE = {"error": "\033[31;1m", "warn": "\033[33;1m", "info": "\033[36m",
         "dim": "\033[2m", "bold": "\033[1m", "ok": "\033[32m"}
UNI = {"error": "\u2716", "warn": "\u26a0", "info": "\u2139", "dot": "\u00b7", "arrow": "\u2192",
       "ok": "\u2714"}
ASCII = {"error": "x", "warn": "!", "info": "i", "dot": "-", "arrow": "->", "ok": "+"}
LABEL = {"error": "ERROR", "warn": "WARN", "info": "NOTE"}


def stdout_supports_unicode() -> bool:
    enc = (getattr(sys.stdout, "encoding", None) or "").lower().replace("-", "")
    return enc in ("utf8", "utf8sig")


class Painter:
    def __init__(self, color: bool, unicode: bool) -> None:
        self.color = color
        self.sym = UNI if unicode else ASCII

    def c(self, style: str, text: str) -> str:
        return "%s%s%s" % (STYLE[style], text, RESET) if self.color else text


def agent_argv_desc(shell: str, mode: str) -> str:
    return {"human": "%s -l -i", "login": "%s -l -c", "interactive": "%s -i -c",
            "plain": "%s -c", "bare": "env -i HOME=... %s -c"}[mode] % shell


def mode_matrix(snaps: Dict[str, Dict[str, Any]]) -> List[List[str]]:
    rows = [["mode", "ok", "PATH dirs", "tools", "proxy", "UTF-8", "SSH sock", "aliases"]]
    for mode, s in snaps.items():
        if not s.get("ok"):
            rows.append([mode, "FAILED"] + ["-"] * 6)
            continue
        proxies = sum(1 for n in s["vars"] if n.lower().endswith("_proxy") and n.lower() != "no_proxy")
        u = s["locale"]["utf8"]
        paths = [t for t in s["tools"].values() if t["kind"] == "path"]
        rows.append([
            mode, "yes", str(len(s["path"])), str(len(paths)), str(proxies) if proxies else "-",
            "yes" if u else ("NO" if u is False else "?"),
            "yes" if (s["vars"].get("SSH_AUTH_SOCK") and s["ssh_sock_ok"]) else "-",
            str(s["aliases"]) if s["aliases"] is not None else "?"])
    return rows


def _table(rows: List[List[str]], indent: str = "  ") -> List[str]:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    out = []
    for n, r in enumerate(rows):
        out.append(indent + "  ".join(c.ljust(widths[i]) for i, c in enumerate(r)).rstrip())
        if n == 0:
            out.append(indent + "  ".join("-" * w for w in widths))
    return out


def _wrap(label: str, text: str, width: int = 104) -> List[str]:
    first = "      %-6s " % label
    rest = " " * len(first)
    lines = textwrap.wrap(text, width=width, initial_indent=first, subsequent_indent=rest,
                          break_long_words=False, break_on_hyphens=False)
    return lines or [first.rstrip()]


def render_shell_text(res: Dict[str, Any], p: Painter) -> str:
    snaps = res["modes"]
    shell = res["shell"]
    am = res["agent_mode"]
    findings: List[Finding] = res["findings"]
    home = res["home"]
    sm = summarize(findings)
    L: List[str] = []
    sym = p.sym
    hs = snaps["human"]
    if res.get("demo"):
        L.append(p.c("warn", "DEMO") + " " + (
            "scripted fake environments; no shell was started and nothing on this machine was inspected"
            if res["demo"] == "scripted" else
            "real %s against a temporary fake HOME (shown as %s); your own dotfiles were not read"
            % (shell, home)))
        L.append("")
    L.append(p.c("bold", "shellparity %s" % __version__) + "  %s  your terminal vs the agent's shell"
             % sym["dot"])
    ver = hs.get("shell_version") or ""
    L.append("  shell    %s %s (%s)" % (shell, ver.split("(")[0], res["shell_path"]))
    L.append("  human    %-20s %s" % (agent_argv_desc(shell, "human"), MODE_HELP["human"]))
    L.append("  agent    %-20s %s" % (agent_argv_desc(shell, am), MODE_HELP[am]))
    L.append("")
    if not hs["ok"] or not snaps[am]["ok"]:
        for m in ("human", am):
            if not snaps[m]["ok"]:
                L.append(p.c("error", "  %s probe failed (%s): %s" % (m, agent_argv_desc(shell, m),
                                                                   snaps[m]["error"])))
        L.append("")
        L.append("  Nothing can be compared. Run with --verbose to see the shell's own output.")
        return "\n".join(L)
    ident = res.get("identical_tools", 0)
    parts = [
        p.c("error", "%d error%s" % (sm["error"], "" if sm["error"] == 1 else "s"))
        if sm["error"] else "0 errors",
        p.c("warn", "%d warning%s" % (sm["warn"], "" if sm["warn"] == 1 else "s"))
        if sm["warn"] else "0 warnings",
        "%d note%s" % (sm["info"], "" if sm["info"] == 1 else "s")]
    L.append("  " + ("  %s  " % sym["dot"]).join(parts)
             + p.c("dim", "   (%d tools resolve identically)" % ident))
    L.append("")
    if not findings:
        L.append("  %s Both shells see the same PATH, tools, proxy, locale, SSH and git setup."
                 % p.c("ok", sym["ok"]))
        L.append("")
    pl = res.get("placement") or {}
    if pl and pl.get("fixable"):
        L.append(p.c("bold", "  Where the fixes go"))
        if pl.get("target"):
            L.extend(textwrap.wrap("%s: %s." % (pl["target"], pl["reason"]), width=104,
                                   initial_indent="    ", subsequent_indent="      ",
                                   break_long_words=False))
        else:
            L.extend(textwrap.wrap(pl["reason"] + ".", width=104, initial_indent="    ",
                                   subsequent_indent="      ", break_long_words=False))
        flag = {"login": "-l", "interactive": "-i"}
        for m, n_ in (pl.get("shortcuts") or {}).items():
            L.extend(textwrap.wrap(
                "Alternative: start the agent's shell as `%s %s -c ...` (%s mode). It already "
                "sees the fix for %d finding%s below, but it runs your %s startup files on every "
                "command (slower, may print banners)." % (
                    shell, flag[m], m, n_, "" if n_ == 1 else "s", m),
                width=104, initial_indent="    ", subsequent_indent="      ",
                break_long_words=False))
        L.append("")
    for n, f in enumerate(findings, 1):
        head = "%s %-5s" % (sym[f.severity], LABEL[f.severity])
        L.append(" %s  %s %s" % (p.c(f.severity, head), p.c("dim", "#%d" % n), p.c("bold", f.title)))
        if f.human:
            L.extend(_wrap("human", f.human))
        if f.agent:
            L.extend(_wrap("agent", f.agent))
        if f.detail:
            L.extend(_wrap("why", f.detail))
        for w in f.where:
            L.extend(_wrap("found", w))
        first = True
        for line in f.fix:
            if line.startswith("    "):
                L.append("      " + " " * 7 + line)
            else:
                L.extend(_wrap("fix" if first else "", line))
                first = False
        L.append("")
    L.append(p.c("bold", "  What each startup mode sees"))
    L.extend(_table(mode_matrix(snaps)))
    L.append("")
    L.append(p.c("bold", "  Startup files read by %s" % shell))
    for row in res["startup"]:
        mark = "yes" if row["exists"] else ("n/a" if row["exists"] is None else "no ")
        extra = ""
        if row.get("guard_line"):
            extra = p.c("warn", "  interactive-only guard at line %d" % row["guard_line"])
        L.append("    %-16s %s  %s%s" % (row["file"], mark, p.c("dim", row["note"]), extra))
    for row in res["startup"]:
        if row.get("guard_line") and shell == "bash":
            L.extend(textwrap.wrap(
                "Note: %s returns early for non-interactive shells (line %d). Anything below that "
                "line is skipped whenever the file is sourced non-interactively (BASH_ENV, scripts, "
                "ssh commands), so do not point BASH_ENV at it; use a separate file."
                % (row["file"], row["guard_line"]), width=104, initial_indent="    ",
                subsequent_indent="      ", break_long_words=False))
    L.append("")
    L.append(p.c("dim", "  Nothing was changed on disk. Fixes above are suggestions; --write-snippet FILE "
                        "saves the export lines."))
    return "\n".join(L)


def render_text(results: List[Dict[str, Any]], color: bool, unicode: bool) -> str:
    p = Painter(color, unicode)
    return "\n\n".join(render_shell_text(r, p) for r in results) + "\n"


# ---------------------------------------------------------------- markdown

def render_markdown(results: List[Dict[str, Any]]) -> str:
    L = ["# Agent shell environment notes", "",
         "_Generated by shellparity %s. Paste this into your agent's context file "
         "(AGENTS.md / CLAUDE.md) or keep it as AGENT_ENV.md._" % __version__, ""]
    for res in results:
        shell = res["shell"]
        am = res["agent_mode"]
        findings: List[Finding] = res["findings"]
        sm = summarize(findings)
        L += ["## %s (agent mode: `%s`)" % (shell, am), "",
              "%d errors, %d warnings, %d notes." % (sm["error"], sm["warn"], sm["info"]), ""]
        if not res["modes"]["human"]["ok"] or not res["modes"][am]["ok"]:
            L += ["Probe failed; nothing compared.", ""]
            continue
        for f in findings:
            L.append("- **%s** %s" % (f.severity.upper(), f.title))
            if f.human:
                L.append("  - human: `%s`" % f.human)
            if f.agent:
                L.append("  - agent: `%s`" % f.agent)
            if f.detail:
                L.append("  - why: %s" % f.detail)
            snippet = f.data.get("snippet")
            if snippet:
                L.append("  - fix:")
                L.append("    ```sh")
                L += ["    " + s for s in snippet]
                L.append("    ```")
            elif f.fix:
                L.append("  - fix: " + " ".join(x.strip() for x in f.fix))
        L.append("")
    return "\n".join(L) + "\n"


# -------------------------------------------------------------------- json

def render_json(results: List[Dict[str, Any]], extra: Optional[Dict[str, Any]] = None) -> str:
    out = []
    for r in results:
        out.append({
            "shell": r["shell"], "shell_path": r["shell_path"], "agent_mode": r["agent_mode"],
            "summary": summarize(r["findings"]),
            "findings": [f.to_dict() for f in r["findings"]],
            "placement": r.get("placement", {}),
            "modes": r["modes"], "startup_files": r["startup"],
            "project_requirements": r.get("requirements", []),
        })
    doc: Dict[str, Any] = {"tool": "shellparity", "version": __version__, "results": out}
    doc.update(extra or {})
    return json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=False)


# ----------------------------------------------------------------- snippet

def render_snippet(results: List[Dict[str, Any]]) -> str:
    L = ["# Generated by shellparity %s - REVIEW before use." % __version__,
         "# Exports that make the agent shell match your terminal shell where shellparity",
         "# could state the value. Secrets are never written. Source this from the file",
         "# shellparity named in its report (e.g. ~/.zshenv, or $BASH_ENV for bash)."]
    seen = set()
    for res in results:
        for f in res["findings"]:
            for line in f.data.get("snippet", []):
                if line not in seen:
                    seen.add(line)
                    L.append(line)
    return "\n".join(L) + "\n"


def compact_home(text: str, home: str) -> str:
    return text.replace(home.rstrip("/") + "/", "~/") if home else text


__all__ = ["render_text", "render_markdown", "render_json", "render_snippet",
           "stdout_supports_unicode", "tilde"]
