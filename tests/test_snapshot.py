from shellparity.probe import PERSIAN_PROBE, build_probe
from shellparity.snapshot import (extract_version, failed_snapshot, interesting_env_names,
                                  is_secret_name, mask_text, mask_value, parse_records,
                                  snapshot_from_records)


def test_parse_records_ignores_noise_lines():
    text = "Welcome!\x1b[0m\nSP\tpath\t/a:/b\nrandom\nSP\tdone\t1\nSP\tempty\t\n"
    rec = parse_records(text)
    assert rec == {"path": "/a:/b", "done": "1", "empty": ""}


def test_extract_version_variants():
    assert extract_version("v22.4.0") == "22.4.0"
    assert extract_version("Python 3.11.2") == "3.11.2"
    assert extract_version("go version go1.22.1 linux/amd64") == "1.22.1"
    assert extract_version("OpenSSH_9.2p1 Debian-2") == "9.2"
    assert extract_version('openjdk version "17.0.2" 2022-01-18') == "17.0.2"
    assert extract_version("no digits here") is None
    assert extract_version("") is None


def test_mask_proxy_credentials():
    assert mask_text("http://user:pw@127.0.0.1:1080") == "http://***:***@127.0.0.1:1080"
    assert mask_text("http://token@host/x") == "http://***@host/x"
    assert mask_text("http://127.0.0.1:1080") == "http://127.0.0.1:1080"


def test_secret_names_never_keep_values():
    for name in ("OPENAI_API_KEY", "GITHUB_TOKEN", "DB_PASSWORD", "AWS_SECRET_ACCESS_KEY",
                 "MY_PAT", "SSH_PRIVATE_KEY", "STRIPE_KEY"):
        assert is_secret_name(name), name
        assert mask_value(name, "hunter2") == "<set>"
    for name in ("PATH", "HTTPS_PROXY", "SSH_AUTH_SOCK", "EDITOR", "KEYBOARD_LAYOUT"):
        assert not is_secret_name(name), name


def _rec(**extra):
    base = {"path": "/usr/bin:/bin", "done": "1", "flags": "hB", "persian_chars": "4",
            "envnames": "HOME PATH FOO", "aliases": "0"}
    base.update({k.replace("__", ":"): v for k, v in extra.items()})
    return base


def test_snapshot_tools_and_versions():
    snap = snapshot_from_records("plain", "bash", _rec(
        tool__node__where="/opt/n/bin/node", tool__node__rc="0", tool__node__ver="v20.1.0",
        tool__ll__where="alias ll='ls -l'"))
    node = snap["tools"]["node"]
    assert node == {"kind": "path", "where": "/opt/n/bin/node", "rc": 0,
                    "raw": "v20.1.0", "version": "20.1.0"}
    assert snap["tools"]["ll"]["kind"] == "other"
    assert snap["tools"]["ll"]["version"] is None


def test_unexported_variables_are_dropped():
    snap = snapshot_from_records("plain", "bash", _rec(
        envnames="HOME PATH EXPORTED", var__EXPORTED="1", var__NOT_EXPORTED="2"))
    assert "EXPORTED" in snap["vars"] and "NOT_EXPORTED" not in snap["vars"]


def test_snapshot_masks_values():
    snap = snapshot_from_records("human", "bash", _rec(
        envnames="HTTPS_PROXY OPENAI_API_KEY", var__HTTPS_PROXY="http://u:p@h:1",
        var__OPENAI_API_KEY="sk-live-abc"))
    assert snap["vars"]["HTTPS_PROXY"] == "http://***:***@h:1"
    assert snap["vars"]["OPENAI_API_KEY"] == "<set>"
    assert "sk-live-abc" not in repr(snap)


def test_utf8_detection_from_character_count():
    assert snapshot_from_records("m", "bash", _rec(persian_chars="4"))["locale"]["utf8"] is True
    assert snapshot_from_records("m", "bash", _rec(persian_chars="8"))["locale"]["utf8"] is False
    assert snapshot_from_records("m", "bash", _rec(persian_chars="6"))["locale"]["utf8"] is None
    assert snapshot_from_records("m", "bash", _rec(persian_chars="x"))["locale"]["utf8"] is None


def test_interactive_flag_and_ok():
    assert snapshot_from_records("human", "bash", _rec(flags="himBHs"))["interactive"] is True
    assert snapshot_from_records("plain", "bash", _rec(flags="hB"))["interactive"] is False
    rec = _rec()
    del rec["done"]
    assert snapshot_from_records("plain", "bash", rec)["ok"] is False


def test_failed_snapshot_shape():
    s = failed_snapshot("human", "zsh", "boom")
    assert s["ok"] is False and s["error"] == "boom" and s["tools"] == {} and s["path"] == []


def test_noise_env_names_filtered():
    names = ["PATH", "_", "SHLVL", "XDG_SESSION_ID", "MY_THING", "LESSOPEN", "P9K_TTY"]
    assert interesting_env_names(names) == ["PATH", "MY_THING"]


def test_probe_has_no_secret_values_requested():
    script = build_probe()
    assert PERSIAN_PROBE in script
    # only allow-listed names are read; no generic "dump all values" command
    assert "printenv" not in script
    assert "command env 2>/dev/null | command sed -n 's/^\\([A-Za-z_][A-Za-z0-9_]*\\)=.*/\\1/p'" in script
    for name in ("OPENAI_API_KEY", "GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY"):
        assert name not in script


def test_probe_extra_tools_are_validated():
    script = build_probe(extra_tools=["mytool", "bad;rm -rf /", "ok-tool_2"])
    assert " mytool" in script and "ok-tool_2" in script and "rm -rf" not in script
    only = build_probe(only_tools=["node"])
    assert "for sp_t in node; do" in only


def test_redact_line_hides_secret_assignments_and_url_credentials():
    from shellparity.snapshot import redact_line
    assert redact_line('export OPENAI_API_KEY="sk-live-abc def"') == 'export OPENAI_API_KEY=<redacted>'
    assert redact_line("export GITHUB_TOKEN=ghp_abc123 # note") == "export GITHUB_TOKEN=<redacted> # note"
    assert redact_line("export X=1 DB_PASSWORD='p w' Y=2") == "export X=1 DB_PASSWORD=<redacted> Y=2"
    assert redact_line("export HTTPS_PROXY=http://u:p@h:1") == "export HTTPS_PROXY=http://***:***@h:1"
    assert redact_line("export EDITOR=vim") == "export EDITOR=vim"
