# Contributing

Thanks for helping. shellparity is deliberately small: Python 3.9+, standard library only.

```sh
git clone https://github.com/mrzroot/shellparity && cd shellparity
python -m venv .venv && . .venv/bin/activate
pip install -e '.[test]'
pytest
```

- Tests that spawn shells use a throw-away `HOME` in `tmp_path`; they never touch your real
  dotfiles. Tests for shells that are not installed are skipped (install `zsh` to run them all).
- New detections need: a pure rule in `shellparity/compare.py`, a unit test with hand-written
  snapshots, and, if it depends on shell behaviour, a real-shell test. Do not add a check to
  the README until it is implemented and tested.
- Never read or print secret values. Variable *names* may be compared; values only for the
  allow-list in `shellparity/probe.py`, and always masked.
- If you know a tool that already does this, please open an issue so it can be linked.
