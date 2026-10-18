import os

import pytest

from shellparity.advise import (AdviceContext, RcFile, advise, find_guard, home_var,
                                locate, manager_for, manager_lines, placement, scan_rc_files,
                                snippet_for, startup_report, target_for, tilde)
from shellparity.compare import compare
from shellparity.snapshot import snapshot_from_records
from test_compare import by_id, snap


def test_find_guard_variants():
    cases = {
        "case $- in\n    *i*) ;;\n      *) return;;\nesac\n": 1,
        "[[ $- != *i* ]] && return\n": 1,
        "[ -z \"$PS1\" ] && return\n": 1,
        "[[ -z $PS1 ]] && return\n": 1,
        "[[ $- == *i* ]] || return\n": 1,
        "# [[ $- != *i* ]] && return\nexport A=1\n": None,
        "export A=1\n": None,
    }
    for text, want in cases.items():
        assert find_guard(text.splitlines()) == want, text


def test_scan_rc_files_follows_one_source_and_finds_guard(tmp_path):
    (tmp_path / ".bashrc").write_text(
        "# comment\n[[ $- != *i* ]] && return\nsource %s/extra.sh\nexport A=1\n" % tmp_path)
    (tmp_path / "extra.sh").write_text("export B=2\n")
    files = scan_rc_files("bash", str(tmp_path))
    names = [f.display for f in files]
    assert "~/.bashrc" in names and "~/extra.sh" in names
    rc = next(f for f in files if f.display == "~/.bashrc")
    assert rc.guard_line == 2
    assert next(f for f in files if f.display == "~/extra.sh").sourced_from == "~/.bashrc"


def test_scan_rc_files_handles_missing_and_source_loops(tmp_path):
    assert scan_rc_files("zsh", str(tmp_path)) == []
    (tmp_path / ".zshrc").write_text("source %s/.zshrc\n" % tmp_path)
    assert len(scan_rc_files("zsh", str(tmp_path))) == 1


def _ctx(tmp_path, shell="bash", mode="plain", rc=None, snaps=None, platform="linux"):
    ctx = AdviceContext(shell=shell, home=str(tmp_path), agent_mode=mode,
                        snaps=snaps or {}, platform=platform)
    ctx.files = scan_rc_files(shell, str(tmp_path)) if rc is None else rc
    return ctx


def test_target_per_shell_and_mode(tmp_path):
    assert target_for(_ctx(tmp_path, "zsh", "plain"))[0] == "~/.zshenv"
    assert target_for(_ctx(tmp_path, "zsh", "login"))[0] == "~/.zshenv"
    assert target_for(_ctx(tmp_path, "bash", "plain"))[0] == "~/.bash_env"
    assert target_for(_ctx(tmp_path, "bash", "interactive"))[0] == "~/.bashrc"
    assert target_for(_ctx(tmp_path, "bash", "login"))[0] == "~/.profile"
    (tmp_path / ".bash_profile").write_text("")
    assert target_for(_ctx(tmp_path, "bash", "login"))[0] == "~/.bash_profile"
    target, reason = target_for(_ctx(tmp_path, "sh", "plain"))
    assert target == "" and "no startup file" in reason
    assert target_for(_ctx(tmp_path, "sh", "login"))[0] == "~/.profile"


def test_manager_detection_and_lines(tmp_path):
    ctx = _ctx(tmp_path)
    assert manager_for("/home/u/.nvm/versions/node/v22/bin/node") == "nvm"
    assert manager_for("/home/u/.pyenv/shims/python") == "pyenv"
    assert manager_for("/opt/homebrew/bin/git") == "brew"
    assert manager_for("/usr/bin/git") == ""
    assert "PYENV_ROOT" in manager_lines("pyenv", "/h/.pyenv/shims/python", ctx)[0]
    assert manager_lines("", "/opt/x/bin/tool", ctx) == ['export PATH="/opt/x/bin:$PATH"']
    assert manager_lines("fnm", "/x", ctx) == ['eval "$(fnm env)"']


def test_home_var_and_tilde():
    assert home_var("/home/u/bin", "/home/u") == "$HOME/bin"
    assert home_var("/opt/bin", "/home/u") == "/opt/bin"
    assert tilde("/home/u/.zshrc", "/home/u") == "~/.zshrc"
    assert tilde("/home/user2/.zshrc", "/home/u") == "/home/user2/.zshrc"


def _rc(text, name="~/.bashrc", home="/home/u"):
    lines = text.splitlines()
    return RcFile(home + name[1:], name, lines, find_guard(lines))


def test_locate_finds_variable_definition_and_marks_guard(tmp_path):
    rc = _rc("[[ $- != *i* ]] && return\nexport FOO=1\nexport HTTPS_PROXY=http://u:p@h:1\n"
             "# export OTHER=3\n")
    h = snap("human", var__HTTPS_PROXY="http://u:p@h:1")
    f = by_id(compare(h, snap()), "proxy.missing")
    ctx = _ctx(tmp_path, rc=[rc], snaps={"human": h, "plain": snap()})
    hits = locate(f, ctx)
    assert len(hits) == 1
    assert hits[0].startswith("~/.bashrc:3: export HTTPS_PROXY=http://***:***@h:1")
    assert "below the interactive-only guard at line 1" in hits[0]
    assert "u:p@" not in hits[0]


def test_locate_ignores_commented_lines_and_finds_path_entries(tmp_path):
    rc = _rc('# export PATH="$HOME/.cargo/bin:$PATH"\nexport PATH="$HOME/.local/bin:$PATH"\n',
             home=str(tmp_path))
    h = snap("human", path="%s/.local/bin:%s/.cargo/bin:/usr/bin:/bin" % (tmp_path, tmp_path))
    f = by_id(compare(h, snap()), "path.missing")
    hits = locate(f, _ctx(tmp_path, rc=[rc]))
    assert len(hits) == 1 and ".local/bin" in hits[0] and ":2:" in hits[0]


def test_snippet_uses_home_var_and_platform_locale(tmp_path):
    h = snap("human", path="%s/.local/bin:/usr/bin:/bin" % tmp_path)
    f = by_id(compare(h, snap()), "path.missing")
    assert snippet_for(f, _ctx(tmp_path)) == ['export PATH="$HOME/.local/bin:$PATH"']
    f2 = by_id(compare(snap("human"), snap(persian_chars="8")), "locale")
    assert snippet_for(f2, _ctx(tmp_path, platform="linux")) == ["export LANG=C.UTF-8"]
    assert snippet_for(f2, _ctx(tmp_path, platform="darwin")) == ["export LANG=en_US.UTF-8"]
    # prefer the human shell's own UTF-8 locale
    hh = snap("human", var__LANG="de_DE.UTF-8")
    f3 = by_id(compare(hh, snap(persian_chars="8")), "locale")
    ctx = _ctx(tmp_path, snaps={"human": hh, "plain": snap()})
    assert snippet_for(f3, ctx) == ["export LANG=de_DE.UTF-8"]


def test_credentials_are_never_emitted_in_fix_lines(tmp_path):
    rc = _rc("export HTTPS_PROXY=http://user:pw@h:1\n")
    h = snapshot_from_records("human", "bash", {
        "path": "/usr/bin", "done": "1", "persian_chars": "4", "flags": "himBH",
        "envnames": "HTTPS_PROXY", "var:HTTPS_PROXY": "http://user:pw@h:1"})
    fs = compare(h, snap())
    ctx = _ctx(tmp_path, rc=[rc], snaps={"human": h, "plain": snap()})
    advise(fs, ctx)
    text = "\n".join(l for f in fs for l in f.fix + f.where)
    assert "pw" not in text and "user:" not in text
    assert "contains credentials" in text


def test_advise_dedupes_identical_snippets(tmp_path):
    h = snap("human", tools={
        "node": ("/h/.nvm/v22/bin/node", 0, "v22.4.0"),
        "npm": ("/h/.nvm/v22/bin/npm", 0, "10.8.1")},
        path="/h/.nvm/v22/bin:/usr/bin:/bin")
    a = snap(tools={"node": ("/usr/bin/node", 0, "v12.1.0")})
    fs = compare(h, a)
    ctx = _ctx(tmp_path, rc=[], snaps={"human": h, "plain": a})
    ctx.home = "/h"
    advise(fs, ctx)
    text = [("\n".join(f.fix)) for f in fs if f.id.startswith("tool.")]
    assert any("Same lines as finding #" in t for t in text)
    assert any("nvm is a shell function" in t for t in text)


def test_visible_in_and_placement_shortcuts(tmp_path):
    h = snap("human", var__JAVA_HOME="/jdk")
    login = snap("login", var__JAVA_HOME="/jdk")
    plain = snap("plain")
    fs = compare(h, plain)
    ctx = _ctx(tmp_path, rc=[], snaps={"human": h, "plain": plain, "login": login})
    advise(fs, ctx)
    f = by_id(fs, "env.missing:JAVA_HOME")
    assert f.visible_in == ["login"]
    pl = placement(ctx, fs)
    assert pl["shortcuts"] == {"login": 1} and pl["target"] == "~/.bash_env"


def test_startup_report_flags_guard(tmp_path):
    (tmp_path / ".bashrc").write_text("[[ $- != *i* ]] && return\n")
    ctx = _ctx(tmp_path, snaps={"plain": snap()})
    rows = {r["file"]: r for r in startup_report(ctx)}
    assert rows["~/.bashrc"]["exists"] is True and rows["~/.bashrc"]["guard_line"] == 1
    assert rows["~/.bash_profile"]["exists"] is False
    assert rows["$BASH_ENV"]["exists"] is None
