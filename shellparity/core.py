"""Orchestration: probe the shell modes, compare, advise."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Sequence

from .advise import AdviceContext, advise, placement, scan_rc_files, startup_report
from .compare import compare
from .project import detect_requirements
from .runner import MODES, run_modes, shell_basename


def identical_tool_count(h: Dict[str, Any], a: Dict[str, Any]) -> int:
    n = 0
    for name, ht in h["tools"].items():
        at = a["tools"].get(name)
        if at and ht["kind"] == "path" and at["kind"] == "path" and \
                ht["where"] == at["where"] and ht["version"] == at["version"]:
            n += 1
    return n


def analyze_snapshots(snaps: Dict[str, Dict[str, Any]], shell: str, shell_path: str,
                      agent_mode: str, home: str,
                      requirements: Optional[List[Dict[str, str]]] = None,
                      rc_files: Optional[list] = None) -> Dict[str, Any]:
    """Compare already-collected snapshots (used by the live run, tests and demo)."""
    res: Dict[str, Any] = {
        "shell": shell, "shell_path": shell_path, "agent_mode": agent_mode, "home": home,
        "modes": snaps, "findings": [], "startup": [], "requirements": requirements or [],
        "identical_tools": 0, "placement": {},
    }
    h, a = snaps["human"], snaps[agent_mode]
    ctx = AdviceContext(shell=shell, home=home, agent_mode=agent_mode, snaps=snaps)
    ctx.files = rc_files if rc_files is not None else scan_rc_files(shell, home)
    res["startup"] = startup_report(ctx)
    if not (h["ok"] and a["ok"]):
        return res
    findings = compare(h, a, requirements)
    advise(findings, ctx)
    res["findings"] = findings
    res["placement"] = placement(ctx, findings)
    res["identical_tools"] = identical_tool_count(h, a)
    return res


def analyze(shell_path: str, agent_mode: str = "plain", *, modes: Sequence[str] = MODES,
            project_dir: Optional[str] = None, extra_tools: Optional[Sequence[str]] = None,
            inherit_env: bool = False, home: Optional[str] = None,
            extra_env: Optional[Dict[str, str]] = None, timeout: float = 30.0,
            only_tools: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    use_modes = list(dict.fromkeys(["human", agent_mode] + list(modes)))
    real_home = home or os.environ.get("HOME") or os.path.expanduser("~")
    project_dir = project_dir or os.getcwd()
    snaps = run_modes(shell_path, use_modes, extra_tools=extra_tools, inherit_env=inherit_env,
                      home=real_home, extra_env=extra_env, timeout=timeout, cwd=project_dir,
                      only_tools=only_tools)
    reqs = detect_requirements(project_dir)
    return analyze_snapshots(snaps, shell_basename(shell_path), shell_path, agent_mode,
                             real_home, reqs)
