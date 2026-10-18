# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-18

First release.

### Added
- Probe that runs one POSIX `sh` script in five startup modes (`human` on a pseudo-terminal,
  `login`, `interactive`, `plain`, `bare`) for bash, zsh and sh, with a per-mode timeout.
- Comparison of PATH, 27 common tools (resolution and `--version`), project version
  requirements (`.nvmrc`, `.node-version`, `.python-version`, `.tool-versions`,
  `package.json` engines, `pyproject.toml` requires-python), proxy variables, locale and a
  real UTF-8 test, `SSH_AUTH_SOCK`, git config and commit-signing prerequisites, TTY/TERM,
  selected environment variables, secret-looking variable names (names only), aliases,
  umask, `ulimit -n` and timezone.
- Findings ranked `error` / `warn` / `note`, each with the rc-file line that defines the
  human-side value (textual search), and a printed fix targeted at the right file for the
  shell and agent mode (`~/.zshenv`, `$BASH_ENV` file, `~/.profile`, ...).
- Detection of interactive-only early returns in `~/.bashrc`.
- Output modes: human report, `--json`, `--markdown`, `--write-snippet FILE`, `--fail-on`.
- `--demo` (live fake-HOME run, or `scripted`) that works offline.
- `--shell`, `--agent-mode`, `--project`, `--tool`, `--inherit-env`, `--timeout`.
