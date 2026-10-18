import json

import pytest

from shellparity.project import detect_requirements, satisfies


@pytest.mark.parametrize("version,spec,depth,expected", [
    ("22.4.0", ">=18", 1, True),
    ("12.22.9", ">=18", 1, False),
    ("20.1.0", "^20", 1, True),
    ("21.0.0", "^20", 1, False),
    ("18.0.0", "18 || 20", 1, True),
    ("19.0.0", "18 || 20", 1, False),
    ("22.4.0", ">=18 <21", 1, False),
    ("20.1.0", "20.x", 1, True),
    ("22.1.0", "22", 1, True),
    ("3.12.4", "3.12", 2, True),
    ("3.9.1", ">=3.10", 2, False),
    ("3.11.2", "~=3.11", 2, True),
    ("3.13.0", ">=3.9,<3.13", 2, False),
    ("18.2.0", "lts/*", 1, None),
    ("", ">=18", 1, None),
])
def test_satisfies(version, spec, depth, expected):
    assert satisfies(version, spec, depth) is expected


def test_detect_requirements_from_files(tmp_path):
    (tmp_path / ".nvmrc").write_text("v20.11.0\n")
    (tmp_path / ".python-version").write_text("3.12.4\n")
    (tmp_path / "package.json").write_text(json.dumps({"engines": {"node": ">=18"}}))
    (tmp_path / "pyproject.toml").write_text('[project]\nrequires-python = ">=3.10"\n')
    (tmp_path / ".tool-versions").write_text("nodejs 18.19.0 # comment\npython 3.11.1\nruby 3.3\n")
    got = {(r["tool"], r["spec"], r["source"]) for r in detect_requirements(str(tmp_path))}
    assert ("node", "20.11.0", ".nvmrc") in got
    assert ("python", "3.12.4", ".python-version") in got
    assert ("node", ">=18", "package.json engines.node") in got
    assert ("python", ">=3.10", "pyproject.toml requires-python") in got
    assert ("node", "18.19.0", ".tool-versions") in got
    assert not any(t == "ruby" for t, _, _ in got)


def test_detect_requirements_ignores_aliases_and_garbage(tmp_path):
    (tmp_path / ".nvmrc").write_text("lts/iron\n")
    (tmp_path / "package.json").write_text("{not json")
    assert detect_requirements(str(tmp_path)) == []
    assert detect_requirements(str(tmp_path / "missing")) == []
