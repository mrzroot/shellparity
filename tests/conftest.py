import os
import shutil
import stat
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shellparity import core  # noqa: E402


def have(shell):
    return shutil.which(shell) is not None


requires_bash = pytest.mark.skipif(not have("bash"), reason="bash not installed")
requires_zsh = pytest.mark.skipif(not have("zsh"), reason="zsh not installed")
requires_sh = pytest.mark.skipif(not have("sh"), reason="sh not installed")
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX only")


def write(path, text, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    return h


def analyze_home(home, shell="bash", agent_mode="plain", tools=("git",), extra_env=None,
                 timeout=30.0, project=None):
    """Run the real flow against a fake HOME (never the user's real one)."""
    path = shutil.which(shell)
    return core.analyze(path, agent_mode, project_dir=project or str(home),
                        home=str(home), extra_env=extra_env, timeout=timeout,
                        only_tools=list(tools))


def finding_ids(res):
    return [f.id for f in res["findings"]]


def get(res, prefix):
    return [f for f in res["findings"] if f.id.startswith(prefix)]
