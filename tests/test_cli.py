import json
import os
import subprocess
import sys
from pathlib import Path


from conftest import posix_only, requires_bash
from shellparity import __version__
from shellparity.cli import main

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLDEN = os.path.join(os.path.dirname(__file__), "golden", "demo_scripted.txt")


def run_cli(*args, env=None):
    e = dict(os.environ)
    e["PYTHONPATH"] = ROOT + os.pathsep + e.get("PYTHONPATH", "")
    e["NO_COLOR"] = "1"
    e["PYTHONIOENCODING"] = "utf-8"
    e.update(env or {})
    return subprocess.run([sys.executable, "-m", "shellparity"] + list(args),
                          capture_output=True, text=True, env=e, timeout=120)


def test_version_and_help():
    r = run_cli("--version")
    assert r.returncode == 0 and __version__ in r.stdout
    r = run_cli("--help")
    assert r.returncode == 0
    for flag in ("--json", "--demo", "--shell", "--agent-mode", "--fail-on", "--write-snippet",
                 "--markdown"):
        assert flag in r.stdout


def test_scripted_demo_matches_golden_file():
    r = run_cli("--demo", "scripted")
    assert r.returncode == 0
    assert r.stdout == Path(GOLDEN).read_text(encoding="utf-8")


def test_scripted_demo_has_the_expected_story():
    out = run_cli("--demo", "scripted").stdout
    for needle in ("`node`, `npm` are not found in the agent shell",
                   "the agent shell is not UTF-8", "SSH_AUTH_SOCK is missing",
                   "proxy variables set only in the human shell: HTTPS_PROXY",
                   "OPENAI_API_KEY", "Add to ~/.bash_env:", "DEMO scripted fake environments"):
        assert needle in out, needle
    assert "demo:secret" not in out and "sk-demo" not in out


def test_scripted_demo_json_is_valid():
    r = run_cli("--demo", "scripted", "--json")
    doc = json.loads(r.stdout)
    assert doc["demo"] == "scripted"
    res = doc["results"][0]
    assert res["summary"]["error"] >= 1
    ids = [f["id"] for f in res["findings"]]
    assert "locale.agent_not_utf8" in ids and "ssh.agent_missing" in ids
    assert "demo:secret" not in r.stdout and "sk-demo" not in r.stdout


def test_markdown_output():
    out = run_cli("--demo", "scripted", "--markdown").stdout
    assert out.startswith("# Agent shell environment notes")
    assert "```sh" in out and "export LANG=C.UTF-8" in out


def test_fail_on_exit_codes():
    assert run_cli("--demo", "scripted", "--fail-on", "error").returncode == 1
    assert run_cli("--demo", "scripted", "--fail-on", "info").returncode == 1
    assert run_cli("--demo", "scripted").returncode == 0


def test_write_snippet_writes_only_the_named_file(tmp_path):
    target = tmp_path / "snippet.sh"
    r = run_cli("--demo", "scripted", "--write-snippet", str(target))
    assert r.returncode == 0
    text = target.read_text()
    assert "export LANG=C.UTF-8" in text and "REVIEW before use" in text
    assert 'export PATH="$HOME/.nvm/versions/node/v22.4.0/bin' in text
    assert "demo:secret" not in text and "sk-demo" not in text
    assert "contains credentials" in text
    assert sorted(p.name for p in tmp_path.iterdir()) == ["snippet.sh"]


def test_write_snippet_error_is_reported(tmp_path):
    r = run_cli("--demo", "scripted", "--write-snippet", str(tmp_path / "no" / "dir" / "f"))
    assert r.returncode == 2 and "cannot write" in r.stderr


def test_unknown_shell_is_a_clean_error():
    r = run_cli("--shell", "definitely-not-a-shell")
    assert r.returncode == 2
    assert "not found" in r.stderr and "Traceback" not in r.stderr


@posix_only
@requires_bash
def test_live_demo_runs_real_bash_and_hides_secrets():
    r = run_cli("--demo", "live", "--shell", "bash")
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "/home/demo" in out and "sp-demo-" not in out
    assert "~/.bashrc:" in out and "interactive-only guard" in out
    for secret in ("demo:secret", "sk-demo-not-a-real-key"):
        assert secret not in out
    assert "OPENAI_API_KEY" in out and "SSH_AUTH_SOCK is missing" in out
    assert "`node` resolves to a different version" in out or "are not found" in out


@posix_only
@requires_bash
def test_real_run_json_against_this_machine_is_well_formed():
    r = run_cli("--shell", "bash", "--json", "--timeout", "60")
    assert r.returncode == 0, r.stderr
    doc = json.loads(r.stdout)
    res = doc["results"][0]
    assert res["agent_mode"] == "plain" and res["modes"]["human"]["ok"]


@posix_only
@requires_bash
def test_in_process_main_text_report(capsys, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    code = main(["--demo", "scripted"])
    out = capsys.readouterr().out
    assert code == 0 and "shellparity %s" % __version__ in out.splitlines()[2]
