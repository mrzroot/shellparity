"""Command line interface."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Optional, Sequence

from . import __version__
from .compare import SEV_RANK
from .core import analyze
from .demo import run_demo
from .render import (render_json, render_markdown, render_snippet, render_text,
                     stdout_supports_unicode)
from .runner import MODE_HELP, SUPPORTED_SHELLS, available_shells, find_shell, shell_basename

EXIT_OK, EXIT_FINDINGS, EXIT_ERROR = 0, 1, 2

EPILOG = """\
examples:
  shellparity                       compare your login shell: terminal vs `sh -c` style agent
  shellparity --shell all           every supported shell found on this machine
  shellparity --agent-mode login    agent runs `bash -lc` instead of `bash -c`
  shellparity --json                machine-readable report
  shellparity --markdown > AGENT_ENV.md
  shellparity --demo                offline demo with a fake home directory
  shellparity --fail-on error       exit 1 when there is at least one error (CI / hooks)

shellparity only reads. It never edits your rc files; --write-snippet FILE is the
only way it writes, and only to the file you name.
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="shellparity",
        description="Compare what your interactive terminal shell sees with what an agent's "
                    "(non-interactive) shell sees on the same machine, and print the exact fix.",
        epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version="shellparity %s" % __version__)
    p.add_argument("--shell", default=None, metavar="NAME|PATH|all",
                   help="shell to test: bash, zsh, sh, a path, or 'all' (default: $SHELL)")
    p.add_argument("--agent-mode", default="plain", choices=("plain", "login", "interactive", "bare"),
                   help="how the agent's shell is started (default: plain = `<shell> -c`)")
    out = p.add_argument_group("output")
    out.add_argument("--json", action="store_true", help="print the report as JSON")
    out.add_argument("--markdown", action="store_true",
                     help="print a Markdown report to paste into AGENTS.md / AGENT_ENV.md")
    out.add_argument("--write-snippet", metavar="FILE",
                     help="write the suggested export lines to FILE (the only file shellparity writes)")
    out.add_argument("--no-color", action="store_true", help="disable colours (also: NO_COLOR=1)")
    out.add_argument("--verbose", "-v", action="store_true",
                     help="show probe errors and each mode's raw output tail")
    run = p.add_argument_group("probing")
    run.add_argument("--demo", nargs="?", const="auto", choices=("auto", "live", "scripted"),
                     metavar="live|scripted",
                     help="offline demo with fake environments (no changes to your system)")
    run.add_argument("--project", metavar="DIR", default=None,
                     help="project to read node/python version requirements from (default: cwd)")
    run.add_argument("--tool", action="append", default=[], metavar="NAME",
                     help="also compare this command (repeatable)")
    run.add_argument("--inherit-env", action="store_true",
                     help="start every probed shell from this process's environment instead of a "
                          "clean login-like one")
    run.add_argument("--timeout", type=float, default=30.0, metavar="SEC",
                     help="per-mode timeout in seconds (default: 30)")
    p.add_argument("--fail-on", choices=("error", "warn", "info"), default=None,
                   help="exit with status 1 if a finding of at least this severity exists")
    return p


def _pick_shells(arg: Optional[str]) -> List[str]:
    """Resolve --shell into a list of shell paths. Raises ValueError with a clear message."""
    if arg == "all":
        found = list(available_shells().values())
        if not found:
            raise ValueError("no bash, zsh or sh found on PATH")
        return found
    if arg:
        path = find_shell(arg)
        if not path:
            raise ValueError("shell %r not found (supported: %s, or a path)"
                             % (arg, ", ".join(SUPPORTED_SHELLS)))
        return [path]
    env_shell = os.environ.get("SHELL", "")
    if env_shell and shell_basename(env_shell) in SUPPORTED_SHELLS and os.access(env_shell, os.X_OK):
        return [env_shell]
    avail = available_shells()
    for n in SUPPORTED_SHELLS:
        if n in avail:
            return [avail[n]]
    raise ValueError("could not find a supported shell (bash, zsh, sh)")


def _err(msg: str) -> None:
    sys.stderr.write("shellparity: %s\n" % msg)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if sys.platform == "win32" and not args.demo:
        _err("Windows is not supported in v0.1 (needs POSIX shells and pseudo-terminals). "
             "Try it inside WSL.")
        return EXIT_ERROR
    color = (not args.no_color and not os.environ.get("NO_COLOR") and sys.stdout.isatty()
             and os.environ.get("TERM") != "dumb")
    unicode_ok = stdout_supports_unicode()

    results: List[Dict[str, Any]] = []
    try:
        if args.demo:
            kind = args.demo
            shells = None
            if args.shell:
                shells = _pick_shells(args.shell)[0]
            results.append(run_demo(kind, shell_path=shells, timeout=args.timeout))
        else:
            for sh in _pick_shells(args.shell):
                results.append(analyze(sh, args.agent_mode, project_dir=args.project,
                                       extra_tools=args.tool, inherit_env=args.inherit_env,
                                       timeout=args.timeout))
    except ValueError as exc:
        _err(str(exc))
        return EXIT_ERROR
    except RuntimeError as exc:
        _err(str(exc))
        return EXIT_ERROR

    if args.write_snippet:
        try:
            with open(args.write_snippet, "w", encoding="utf-8") as fh:
                fh.write(render_snippet(results))
        except OSError as exc:
            _err("cannot write %s: %s" % (args.write_snippet, exc))
            return EXIT_ERROR

    if args.json:
        text = render_json(results, {"demo": results[0].get("demo")} if args.demo else None)
        sys.stdout.write(text + "\n")
    elif args.markdown:
        sys.stdout.write(render_markdown(results))
    else:
        sys.stdout.write(render_text(results, color, unicode_ok))
        if args.write_snippet:
            sys.stdout.write("Wrote %s\n" % args.write_snippet)
    if args.verbose:
        for r in results:
            for m, s in r["modes"].items():
                if s.get("error") or s.get("stderr_tail"):
                    sys.stderr.write("[%s/%s] error=%s tail=%r\n"
                                     % (r["shell"], m, s.get("error"), s.get("stderr_tail", "")))

    failed = any(not (r["modes"]["human"]["ok"] and r["modes"][r["agent_mode"]]["ok"])
                 for r in results)
    if failed:
        return EXIT_ERROR
    if args.fail_on:
        thr = SEV_RANK[args.fail_on]
        if any(SEV_RANK[f.severity] >= thr for r in results for f in r["findings"]):
            return EXIT_FINDINGS
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
