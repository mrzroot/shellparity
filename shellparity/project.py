"""Read the project's version requirements (node, python) from common files.

Only major (node) and major.minor (python) versions are compared; this is a
deliberately small subset of semver / PEP 440, not a full resolver.
"""

from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional, Tuple

Requirement = Dict[str, str]  # {"tool","spec","source"}


def _read(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def detect_requirements(project_dir: str) -> List[Requirement]:
    reqs: List[Requirement] = []

    def add(tool: str, spec: str, source: str) -> None:
        spec = spec.strip()
        if spec:
            reqs.append({"tool": tool, "spec": spec, "source": source})

    for fname in (".nvmrc", ".node-version"):
        t = _read(os.path.join(project_dir, fname))
        if t and t.strip() and not t.strip().startswith(("lts", "node", "stable")):
            add("node", t.strip().splitlines()[0].lstrip("v"), fname)
    t = _read(os.path.join(project_dir, ".python-version"))
    if t and t.strip():
        first = t.strip().splitlines()[0].strip()
        if re.match(r"^\d+(\.\d+)*", first):
            add("python", first, ".python-version")
    t = _read(os.path.join(project_dir, ".tool-versions"))
    if t:
        for line in t.splitlines():
            parts = line.split("#")[0].split()
            if len(parts) >= 2:
                tool = {"nodejs": "node", "node": "node", "python": "python"}.get(parts[0])
                if tool and re.match(r"^\d", parts[1]):
                    add(tool, parts[1], ".tool-versions")
    t = _read(os.path.join(project_dir, "package.json"))
    if t:
        try:
            eng = json.loads(t).get("engines", {})
            if isinstance(eng, dict) and isinstance(eng.get("node"), str):
                add("node", eng["node"], "package.json engines.node")
        except (ValueError, AttributeError):
            pass
    t = _read(os.path.join(project_dir, "pyproject.toml"))
    if t:
        m = re.search(r'^\s*requires-python\s*=\s*["\']([^"\']+)["\']', t, re.M)
        if m:
            add("python", m.group(1), "pyproject.toml requires-python")
    return reqs


def _ver_tuple(s: str) -> Tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", s)[:3])


_CLAUSE_RE = re.compile(r"^(>=|<=|>|<|==|=|\^|~=|~|!=)?\s*v?(\d+(?:\.(?:\d+|x|\*))*)(?:\.[x*])?$")


def satisfies(version: str, spec: str, depth: int) -> Optional[bool]:
    """Does ``version`` meet ``spec``? ``depth`` is how many components to compare
    (1 for node major, 2 for python major.minor). None means "could not tell"."""
    have = _ver_tuple(version)[:depth]
    if not have:
        return None
    verdicts: List[bool] = []
    for alt in re.split(r"\|\|", spec):
        alt = alt.strip()
        if not alt:
            continue
        toks = [t for t in re.split(r"[\s,]+", alt.replace(">= ", ">=").replace("> ", ">")
                                    .replace("<= ", "<=").replace("< ", "<")) if t]
        ok_all = True
        parsed_any = False
        for tok in toks:
            m = _CLAUSE_RE.match(tok)
            if not m:
                continue
            parsed_any = True
            op, num = m.group(1) or "", m.group(2)
            want = _ver_tuple(num.replace("x", "0").replace("*", "0"))[:depth]
            if not want:
                continue
            if op in ("", "=", "=="):
                ok = have[:len(want)] == want
            elif op == ">=":
                ok = have >= want
            elif op == ">":
                ok = have > want
            elif op == "<=":
                ok = have <= want
            elif op == "<":
                ok = have < want
            elif op == "!=":
                ok = have[:len(want)] != want
            elif op in ("^",):
                ok = have[0] == want[0] and have >= want
            elif op in ("~", "~="):
                ok = have[:max(1, len(want) - 1)] == want[:max(1, len(want) - 1)] and have >= want
            else:
                continue
            ok_all = ok_all and ok
        if parsed_any:
            verdicts.append(ok_all)
    if not verdicts:
        return None
    return any(verdicts)
