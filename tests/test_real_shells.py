"""End-to-end tests that spawn real shells against a fake HOME in tmp_path."""

import json
import os
import shutil
import subprocess

import pytest

from conftest import (analyze_home, get, have, posix_only, requires_bash,
                      requires_sh, requires_zsh, write)
from shellparity.probe import build_probe
from shellparity.render import render_json, render_text
from shellparity.runner import run_modes

pytestmark = posix_only


def utf8_locale_available():
    if not have("bash"):
        return False
    out = subprocess.run(["bash", "-c", "LC_ALL=C.UTF-8 printf '%s' '\u0633\u0644\u0627\u0645' | wc -m"],
                         capture_output=True, text=True).stdout.strip()
    return out == "4"


needs_utf8 = pytest.mark.skipif(not utf8_locale_available(), reason="C.UTF-8 locale unavailable")


# ------------------------------------------------------------------ syntax

@pytest.mark.parametrize("shell", ["bash", "sh", "zsh"])
def test_probe_script_parses_in_every_shell(shell, tmp_path):
    if not have(shell):
        pytest.skip("%s not installed" % shell)
    f = tmp_path / "probe.sh"
    f.write_text(build_probe())
    r = subprocess.run([shell, "-n", str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# -------------------------------------------------------------------- bash

@requires_bash
def test_path_only_in_bashrc_is_found_with_line_number(home):
    write(home / ".bash_profile", "[ -f ~/.bashrc ] && . ~/.bashrc\n")
    write(home / ".bashrc", "# my rc\nexport PATH=\"$HOME/tools/bin:$PATH\"\n")
    (home / "tools" / "bin").mkdir(parents=True)
    res = analyze_home(home)
    f = get(res, "path.missing")[0]
    assert str(home / "tools" / "bin") in f.data["missing"]
    assert any(w.startswith("~/.bashrc:2:") for w in f.where)
    assert "~/.bash_env" in "\n".join(f.fix)
    # bash -i (agent-mode interactive) would see it, bash -c does not
    assert "interactive" in f.visible_in and "login" in f.visible_in


@requires_bash
def test_fake_node_versions_resolve_differently(home, tmp_path):
    sysbin = tmp_path / "sysbin"
    write(sysbin / "node", "#!/bin/sh\necho v12.22.9\n", executable=True)
    nvm = home / ".nvm" / "v22" / "bin"
    write(nvm / "node", "#!/bin/sh\necho v22.4.0\n", executable=True)
    write(home / ".bash_profile", "[ -f ~/.bashrc ] && . ~/.bashrc\n")
    write(home / ".bashrc", 'export PATH="%s:$PATH"\n' % nvm)
    res = analyze_home(home, tools=("node",), extra_env={"PATH": "%s:/usr/bin:/bin" % sysbin})
    f = get(res, "tool.version:node")[0]
    assert f.severity == "error"
    assert f.human.endswith("v22.4.0") and f.agent.endswith("v12.22.9")
    assert any(".bashrc:1" in w for w in f.where)
    assert "nvm is a shell function" in "\n".join(f.fix)
    assert 'export PATH="$HOME/.nvm/v22/bin:$PATH"' in "\n".join(f.fix)


@requires_bash
def test_tool_missing_in_agent_is_error(home):
    tooldir = home / "opt" / "bin"
    write(tooldir / "mytool", "#!/bin/sh\necho mytool 1.2.3\n", executable=True)
    write(home / ".bash_profile", "[ -f ~/.bashrc ] && . ~/.bashrc\n")
    write(home / ".bashrc", 'export PATH="%s:$PATH"\n' % tooldir)
    res = analyze_home(home, tools=("mytool",))
    f = get(res, "tool.missing:mytool")[0]
    assert f.severity == "error" and f.agent == "command not found"
    assert f.human.endswith("(1.2.3)")


@requires_bash
def test_variable_set_only_in_login_file_is_visible_in_login_mode(home):
    write(home / ".profile", "export JAVA_HOME=/opt/jdk\n")
    res = analyze_home(home)
    f = get(res, "env.missing:JAVA_HOME")[0]
    assert f.severity == "warn" and f.visible_in == ["login"]
    assert any(w.startswith("~/.profile:1:") for w in f.where)
    assert res["placement"]["shortcuts"].get("login", 0) >= 1


@requires_bash
def test_interactive_guard_is_reported(home):
    write(home / ".bash_profile", "[ -f ~/.bashrc ] && . ~/.bashrc\n")
    write(home / ".bashrc", "case $- in\n  *i*) ;;\n  *) return;;\nesac\nexport JAVA_HOME=/jdk\n")
    res = analyze_home(home)
    rows = {r["file"]: r for r in res["startup"]}
    assert rows["~/.bashrc"]["guard_line"] == 1
    f = get(res, "env.missing:JAVA_HOME")[0]
    assert any("below the interactive-only guard at line 1" in w for w in f.where)
    assert "do not point BASH_ENV at it" in " ".join(render_text([res], False, True).split())


@requires_bash
@needs_utf8
def test_utf8_only_in_human_rc(home):
    write(home / ".bash_profile", "[ -f ~/.bashrc ] && . ~/.bashrc\n")
    write(home / ".bashrc", "export LANG=C.UTF-8\n")
    res = analyze_home(home, extra_env={"LANG": "C", "LC_ALL": ""})
    f = get(res, "locale.agent_not_utf8")[0]
    assert f.severity == "error"
    assert f.fix and "export LANG=C.UTF-8" in "\n".join(f.fix)
    assert res["modes"]["human"]["locale"]["utf8"] is True
    assert res["modes"]["plain"]["locale"]["utf8"] is False


@requires_bash
def test_proxy_and_secret_handling_end_to_end(home):
    write(home / ".bash_profile", "[ -f ~/.bashrc ] && . ~/.bashrc\n")
    write(home / ".bashrc",
          "export HTTPS_PROXY=http://alice:s3cr3tpw@127.0.0.1:8080\n"
          "export MY_API_KEY=topsecretvalue987\n")
    res = analyze_home(home)
    assert get(res, "proxy.missing")
    assert get(res, "env.secrets_missing")[0].data["names"] == ["MY_API_KEY"]
    everything = render_json([res]) + render_text([res], False, True)
    for secret in ("s3cr3tpw", "topsecretvalue987", "alice:"):
        assert secret not in everything
    assert "MY_API_KEY" in everything


@requires_bash
def test_ssh_agent_socket_only_in_human(home, tmp_path):
    import socket
    sock_path = "/tmp/sp-test-%d.sock" % os.getpid()
    s = socket.socket(socket.AF_UNIX)
    try:
        s.bind(sock_path)
        write(home / ".bash_profile", "[ -f ~/.bashrc ] && . ~/.bashrc\n")
        write(home / ".bashrc", "export SSH_AUTH_SOCK=%s\n" % sock_path)
        res = analyze_home(home)
        f = get(res, "ssh.agent_missing")[0]
        assert f.severity == "warn" and sock_path in f.human
    finally:
        s.close()
        os.unlink(sock_path)


@requires_bash
def test_human_mode_has_a_tty_and_is_interactive(home):
    res = analyze_home(home)
    h, p = res["modes"]["human"], res["modes"]["plain"]
    assert h["ok"] and h["tty"]["stdin"] is True and h["interactive"] is True
    assert p["ok"] and p["tty"]["stdin"] is False and p["interactive"] is False
    assert get(res, "tty.stdin")[0].severity == "info"


@requires_bash
def test_clean_home_has_no_error_or_warning_findings(home):
    res = analyze_home(home, extra_env={"LANG": "C.UTF-8"} if utf8_locale_available() else None)
    bad = [f.id for f in res["findings"] if f.severity in ("error", "warn")]
    # /etc/profile on some systems adds PATH entries; anything else is a real false positive
    assert all(i.startswith(("path.missing", "tool.missing", "locale")) for i in bad), bad


@requires_bash
def test_slow_rc_times_out_without_hanging(home):
    write(home / ".bash_profile", "[ -f ~/.bashrc ] && . ~/.bashrc\n")
    write(home / ".bashrc", "sleep 60\n")
    import time
    t0 = time.monotonic()
    res = analyze_home(home, timeout=3)
    assert time.monotonic() - t0 < 30
    h = res["modes"]["human"]
    assert h["ok"] is False and "timed out" in h["error"]
    assert res["findings"] == []
    text = render_text([res], False, True)
    assert "human probe failed" in text and "Nothing can be compared" in text


@requires_bash
def test_rc_that_exits_is_reported_not_crashed(home):
    write(home / ".bash_profile", "exit 0\n")
    res = analyze_home(home)
    assert res["modes"]["human"]["ok"] is False
    assert "no data" in res["modes"]["human"]["error"]


@requires_bash
def test_alias_is_classified_as_alias(home):
    write(home / ".bash_profile", "[ -f ~/.bashrc ] && . ~/.bashrc\n")
    write(home / ".bashrc", "alias git='echo hijacked'\n")
    res = analyze_home(home, tools=("git",))
    h = res["modes"]["human"]["tools"]["git"]
    assert h["kind"] == "other"
    assert get(res, "tool.alias_shadow:git")


@requires_bash
def test_project_requirement_checked_against_agent_node(home, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".nvmrc").write_text("22\n")
    sysbin = tmp_path / "sysbin"
    write(sysbin / "node", "#!/bin/sh\necho v12.22.9\n", executable=True)
    res = analyze_home(home, tools=("node",), project=str(proj),
                       extra_env={"PATH": "%s:/usr/bin:/bin" % sysbin})
    f = get(res, "project.node")[0]
    assert "v12.22.9" in f.title and f.data["source"] == ".nvmrc"


@requires_bash
def test_never_writes_outside_its_temp_dir(home, tmp_path, monkeypatch):
    scratch = tmp_path / "tmpdir"
    scratch.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(scratch))
    write(home / ".bashrc", "export A=1\n")
    before = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if "tmpdir" not in p.parts)
    mt = {p: p.stat().st_mtime_ns for p in home.rglob("*") if p.is_file()}
    cwd = os.getcwd()
    analyze_home(home)
    after = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if "tmpdir" not in p.parts)
    assert after == before
    assert {p: p.stat().st_mtime_ns for p in home.rglob("*") if p.is_file()} == mt
    assert os.getcwd() == cwd
    assert list(scratch.iterdir()) == []  # temp dir cleaned up


@requires_bash
def test_all_five_modes_run(home):
    snaps = run_modes(shutil.which("bash"), home=str(home), only_tools=["git"], timeout=30)
    assert list(snaps) == ["human", "login", "interactive", "plain", "bare"]
    assert all(s["ok"] for s in snaps.values()), {m: s["error"] for m, s in snaps.items()}
    assert snaps["bare"]["vars"].get("HOME") == str(home)


@requires_bash
def test_json_report_is_valid_and_complete(home):
    write(home / ".profile", "export JAVA_HOME=/jdk\n")
    doc = json.loads(render_json([analyze_home(home)]))
    r = doc["results"][0]
    assert doc["tool"] == "shellparity" and r["shell"] == "bash"
    assert {"error", "warn", "info"} == set(r["summary"])
    f = next(x for x in r["findings"] if x["id"] == "env.missing:JAVA_HOME")
    assert f["severity"] == "warn" and f["visible_in_modes"] == ["login"]
    assert set(r["modes"]) == {"human", "login", "interactive", "plain", "bare"}


# --------------------------------------------------------------------- zsh

@requires_zsh
def test_zsh_rc_only_variable_and_zshenv_fix_target(home):
    write(home / ".zshrc", "export JAVA_HOME=/opt/jdk\nexport PATH=\"$HOME/zbin:$PATH\"\n")
    (home / "zbin").mkdir()
    res = analyze_home(home, shell="zsh")
    f = get(res, "env.missing:JAVA_HOME")[0]
    assert f.severity == "warn" and any(".zshrc:1" in w for w in f.where)
    assert "Add to ~/.zshenv:" in f.fix
    assert get(res, "path.missing")


@requires_zsh
def test_zsh_zshenv_is_visible_to_agent_so_no_finding(home):
    write(home / ".zshenv", "export JAVA_HOME=/opt/jdk\n")
    res = analyze_home(home, shell="zsh")
    assert not get(res, "env.missing:JAVA_HOME")
    assert res["modes"]["plain"]["vars"]["JAVA_HOME"] == "/opt/jdk"


@requires_zsh
def test_zsh_human_mode_is_interactive_with_tty(home):
    res = analyze_home(home, shell="zsh")
    h = res["modes"]["human"]
    assert h["ok"] and h["interactive"] and h["tty"]["stdin"] is True
    # zsh's first-run wizard (no startup files at all) is answered with "q": nothing written
    assert list(home.iterdir()) == []


# ---------------------------------------------------------------------- sh

@requires_sh
def test_posix_sh_probe_runs_and_fix_has_no_startup_file(home):
    write(home / ".profile", "export JAVA_HOME=/opt/jdk\n")
    res = analyze_home(home, shell="sh")
    assert res["modes"]["plain"]["ok"]
    f = get(res, "env.missing:JAVA_HOME")
    if f:  # /bin/sh may be bash or dash; both read ~/.profile when login
        assert "launched" in " ".join(f[0].fix) or f[0].fix == []
        assert res["placement"]["target"] == ""


@requires_zsh
def test_zsh_tools_are_detected_with_versions(home, tmp_path):
    """Regression: `$var:where` is a zsh parameter modifier; the probe must brace names."""
    bindir = tmp_path / "bin"
    write(bindir / "mytool", "#!/bin/sh\necho mytool 3.1.4\n", executable=True)
    write(home / ".zshrc", 'export PATH="%s:$PATH"\n' % bindir)
    res = analyze_home(home, shell="zsh", tools=("mytool",))
    t = res["modes"]["human"]["tools"]["mytool"]
    assert t["where"] == str(bindir / "mytool") and t["version"] == "3.1.4" and t["rc"] == 0
    assert get(res, "tool.missing:mytool")[0].severity == "error"


@requires_bash
@requires_zsh
def test_every_shell_reports_the_same_tool_record_format(home, tmp_path):
    bindir = tmp_path / "bin"
    write(bindir / "mytool", "#!/bin/sh\necho mytool 3.1.4\n", executable=True)
    for shell in ("bash", "zsh", "sh"):
        if not have(shell):
            continue
        snaps = run_modes(shutil.which(shell), ["plain"], home=str(home),
                          extra_env={"PATH": "%s:/usr/bin:/bin" % bindir},
                          only_tools=["mytool"], timeout=30)
        t = snaps["plain"]["tools"].get("mytool")
        assert t and t["version"] == "3.1.4", shell
