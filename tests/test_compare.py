from shellparity.compare import compare, summarize
from shellparity.snapshot import snapshot_from_records


def snap(mode="plain", tools=None, **kw):
    """Hand-written snapshot. tools: {name: (path, rc, version_output)}."""
    rec = {"path": "/usr/bin:/bin", "done": "1", "flags": "himBH" if mode == "human" else "hB", "persian_chars": "4",
           "envnames": "HOME PATH", "aliases": "0", "umask": "0022", "ulimit_n": "1024",
           "tz_abbr": "UTC"}
    envnames = ["HOME", "PATH"]
    for name, (where, rc, ver) in (tools or {}).items():
        rec["tool:%s:where" % name] = where
        rec["tool:%s:rc" % name] = str(rc)
        rec["tool:%s:ver" % name] = ver
    for k, v in kw.items():
        key = k.replace("__", ":")
        if key.startswith("var:"):
            envnames.append(key[4:])
        rec[key] = v
    rec["envnames"] = " ".join(envnames + rec.get("extra_names", "").split())
    return snapshot_from_records(mode, "bash", rec)


def ids(findings):
    return [f.id for f in findings]


def by_id(findings, prefix):
    out = [f for f in findings if f.id.startswith(prefix)]
    assert out, "no finding %s in %s" % (prefix, ids(findings))
    return out[0]


def test_identical_shells_have_no_findings():
    t = {"git": ("/usr/bin/git", 0, "git version 2.43.0")}
    assert compare(snap("human", t), snap("plain", t)) == []


def test_path_entries_only_in_human():
    h = snap("human", path="/home/u/.cargo/bin:/home/u/bin:/usr/bin:/bin")
    f = by_id(compare(h, snap()), "path.missing")
    assert f.severity == "warn"
    assert f.data["missing"] == ["/home/u/.cargo/bin", "/home/u/bin"]
    assert f.present(h) is True and f.present(snap()) is False


def test_path_trailing_slash_is_not_a_difference():
    assert compare(snap("human", path="/usr/bin/:/bin/"), snap(path="/usr/bin:/bin")) == []


def test_tool_missing_is_error_and_grouped_by_directory():
    h = snap("human", tools={
        "node": ("/home/u/.nvm/v22/bin/node", 0, "v22.4.0"),
        "npm": ("/home/u/.nvm/v22/bin/npm", 0, "10.8.1"),
        "git": ("/usr/bin/git", 0, "git version 2.43.0")})
    a = snap(tools={"git": ("/usr/bin/git", 0, "git version 2.43.0")})
    fs = [f for f in compare(h, a) if f.id.startswith("tool.")]
    assert len(fs) == 1 and fs[0].severity == "error"
    assert fs[0].data["tools"] == ["node", "npm"]
    assert "`node`, `npm` are not found" in fs[0].title


def test_major_version_difference_is_error_minor_is_warn():
    h = snap("human", tools={"node": ("/a/node", 0, "v22.4.0"), "git": ("/a/git", 0, "git version 2.43.0")})
    a = snap(tools={"node": ("/b/node", 0, "v12.22.9"), "git": ("/b/git", 0, "git version 2.30.2")})
    fs = compare(h, a)
    assert by_id(fs, "tool.version:node").severity == "error"
    assert by_id(fs, "tool.version:git").severity == "warn"


def test_same_version_different_path_is_info():
    h = snap("human", tools={"curl": ("/opt/homebrew/bin/curl", 0, "curl 8.5.0")})
    a = snap(tools={"curl": ("/usr/bin/curl", 0, "curl 8.5.0")})
    assert by_id(compare(h, a), "tool.path:curl").severity == "info"


def test_same_path_different_version_points_at_selector_variable():
    h = snap("human", tools={"python3": ("/home/u/.pyenv/shims/python3", 0, "Python 3.12.4")})
    a = snap(tools={"python3": ("/home/u/.pyenv/shims/python3", 0, "Python 3.9.2")})
    f = by_id(compare(h, a), "tool.version:python3")
    assert f.data["same_path"] is True and "environment variable" in f.detail


def test_broken_shim_in_agent_is_error():
    h = snap("human", tools={"python": ("/home/u/.pyenv/shims/python", 0, "Python 3.12.4")})
    a = snap(tools={"python": ("/home/u/.pyenv/shims/python", 127,
                               "pyenv: python: command not found")})
    f = by_id(compare(h, a), "tool.broken:python")
    assert f.severity == "error" and "exit 127" in f.agent


def test_alias_only_in_human_is_warn():
    h = snap("human", tools={"python": ("alias python=python3", 0, "")})
    f = by_id(compare(h, snap()), "tool.alias_only:python")
    assert f.severity == "warn"


def test_proxy_only_in_human_is_warn_and_masks_credentials():
    h = snapshot_from_records("human", "bash", {
        "path": "/usr/bin", "done": "1", "persian_chars": "4", "flags": "himBH",
        "envnames": "HTTPS_PROXY https_proxy", "var:HTTPS_PROXY": "http://u:p@10.0.0.1:3128",
        "var:https_proxy": "http://u:p@10.0.0.1:3128"})
    f = by_id(compare(h, snap()), "proxy.missing")
    assert f.severity == "warn" and "p@" not in f.human and "***" in f.human


def test_proxy_value_differs():
    h = snap("human", var__http_proxy="http://a:1", var__HTTP_PROXY="http://a:1")
    a = snap(var__http_proxy="http://b:2", var__HTTP_PROXY="http://b:2")
    assert by_id(compare(h, a), "proxy.differs").severity == "warn"


def test_proxy_case_mismatch_and_no_proxy_notes():
    h = snap("human", var__HTTPS_PROXY="http://a:1")
    fs = compare(h, snap("plain", var__HTTPS_PROXY="http://a:1"))
    assert by_id(fs, "proxy.case:human:https_proxy").data["unset"] == "https_proxy"
    assert by_id(fs, "proxy.no_proxy:agent")
    ok = snap("human", var__https_proxy="http://a:1", var__HTTPS_PROXY="http://a:1",
              var__no_proxy="localhost,127.0.0.1")
    assert not [f for f in compare(ok, ok) if f.area == "proxy"]


def test_locale_agent_not_utf8_is_error_when_human_is():
    a = snap(persian_chars="8", var__LANG="C", charmap="ANSI_X3.4-1968")
    f = by_id(compare(snap("human"), a), "locale.agent_not_utf8")
    assert f.severity == "error" and "NOT UTF-8" in f.agent


def test_locale_both_not_utf8_is_warn():
    h, a = snap("human", persian_chars="8"), snap(persian_chars="8")
    f = by_id(compare(h, a), "locale.agent_not_utf8")
    assert f.severity == "warn" and "neither" in f.title


def test_locale_missing_locale_is_explained():
    a = snap(persian_chars="8", var__LANG="en_US.UTF-8")
    f = by_id(compare(snap("human"), a), "locale.agent_not_utf8")
    assert "probably not installed" in f.detail


def test_locale_lc_all_override_is_explained():
    a = snap(persian_chars="8", var__LC_ALL="C", var__LANG="en_US.UTF-8")
    assert "LC_ALL=C overrides LANG" in by_id(compare(snap("human"), a), "locale").detail


def test_human_not_utf8_is_only_info():
    f = by_id(compare(snap("human", persian_chars="8"), snap()), "locale.human_not_utf8")
    assert f.severity == "info"


def test_ssh_agent_missing_is_warn():
    h = snap("human", var__SSH_AUTH_SOCK="/run/user/1000/agent.sock", ssh_sock_ok="1")
    f = by_id(compare(h, snap()), "ssh.agent_missing")
    assert f.severity == "warn" and f.data["human_value"] == "/run/user/1000/agent.sock"
    both = snap("plain", var__SSH_AUTH_SOCK="/run/user/1000/agent.sock", ssh_sock_ok="1")
    assert not [f for f in compare(h, both) if f.area == "ssh"]


def test_ssh_stale_socket_is_info():
    h = snap("human", var__SSH_AUTH_SOCK="/tmp/gone.sock", ssh_sock_ok="0")
    assert by_id(compare(h, snap()), "ssh.human_stale").severity == "info"


def test_git_signing_without_tty_warns():
    h = snap("human", **{"git:commit.gpgsign": "true", "var:GPG_TTY": "/dev/pts/1"})
    a = snap(**{"git:commit.gpgsign": "true", "tty0": "0"})
    assert by_id(compare(h, a), "git.gpg_tty").severity == "warn"
    quiet = snap(**{"git:commit.gpgsign": "true", "tty0": "0", "var:GPG_TTY": "/dev/pts/9"})
    assert not [f for f in compare(h, quiet) if f.id == "git.gpg_tty"]


def test_git_ssh_signing_needs_agent():
    a = snap(**{"git:commit.gpgsign": "true", "git:gpg.format": "ssh"})
    assert by_id(compare(snap("human"), a), "git.ssh_signing")


def test_git_config_difference():
    h = snap("human", **{"git:user.email": "me@x.org"})
    f = by_id(compare(h, snap()), "git.config:user.email")
    assert f.severity == "warn" and f.agent == "unset"


def test_runtime_var_missing_is_warn_other_is_info():
    h = snap("human", var__JAVA_HOME="/jdk", var__EDITOR="vim")
    fs = compare(h, snap())
    assert by_id(fs, "env.missing:JAVA_HOME").severity == "warn"
    assert by_id(fs, "env.missing:EDITOR").severity == "info"


def test_secret_names_listed_without_values():
    h = snap("human", extra_names="OPENAI_API_KEY GITHUB_TOKEN MY_THING")
    fs = compare(h, snap())
    f = by_id(fs, "env.secrets_missing")
    assert f.severity == "warn" and f.data["names"] == ["GITHUB_TOKEN", "OPENAI_API_KEY"]
    assert "MY_THING" not in f.human
    assert by_id(fs, "env.others_missing").data["names"] == ["MY_THING"]


def test_tty_and_alias_notes_are_info_only():
    h = snap("human", tty0="1", aliases="3", var__TERM="xterm-256color")
    fs = compare(h, snap())
    assert by_id(fs, "tty.stdin").severity == "info"
    assert by_id(fs, "tty.term").severity == "info"
    assert by_id(fs, "misc.aliases").severity == "info"
    assert summarize(fs)["error"] == 0


def test_project_requirement_unmet_in_agent():
    h = snap("human", tools={"node": ("/n22/node", 0, "v22.4.0")})
    a = snap(tools={"node": ("/usr/bin/node", 0, "v12.22.9")})
    reqs = [{"tool": "node", "spec": ">=18", "source": ".nvmrc"}]
    f = by_id(compare(h, a, reqs), "project.node")
    assert f.severity == "error" and f.data["source"] == ".nvmrc"
    # agent fine -> nothing
    assert not [f for f in compare(h, h, reqs) if f.id.startswith("project")]


def test_project_requirement_unmet_everywhere_is_warn():
    h = snap("human", tools={"python3": ("/p", 0, "Python 3.8.10")})
    a = snap(tools={"python3": ("/p", 0, "Python 3.8.10")})
    reqs = [{"tool": "python", "spec": ">=3.10", "source": "pyproject.toml"}]
    assert by_id(compare(h, a, reqs), "project.python").severity == "warn"


def test_findings_sorted_by_severity():
    h = snap("human", tools={"node": ("/n/node", 0, "v22.4.0")}, tty0="1",
             var__JAVA_HOME="/jdk")
    sev = [f.severity for f in compare(h, snap())]
    assert sev == sorted(sev, key=lambda s: -{"error": 3, "warn": 2, "info": 1}[s])


def test_human_probe_not_interactive_is_flagged():
    h = snap("human", flags="hB")
    assert by_id(compare(h, snap()), "probe.human_not_interactive").severity == "warn"


def test_path_presence_ignores_system_dirs_for_visibility():
    h = snap("human", var__HOME="/home/u", path="/home/u/bin:/usr/local/games:/usr/bin:/bin")
    f = by_id(compare(h, snap()), "path.missing")
    interactive = snap("interactive", path="/home/u/bin:/usr/bin:/bin")  # no /usr/local/games
    assert f.present(interactive) is True
