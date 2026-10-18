<div align="center">

# shellparity

**See what your terminal sees vs what an AI agent's shell sees, and get the exact fix.**

[![CI](https://github.com/mrzroot/shellparity/actions/workflows/ci.yml/badge.svg)](https://github.com/mrzroot/shellparity/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.9%2B-blue)
![deps](https://img.shields.io/badge/dependencies-none-brightgreen)
![license](https://img.shields.io/badge/license-MIT-lightgrey)

English · [فارسی](README.fa.md)

</div>

```text
 ✖ ERROR  #1 `node`, `npm` are not found in the agent shell
      human  /home/demo/.nvm/versions/node/v22.4.0/bin/node (22.4.0)
      agent  command not found
      why    `command -v node` finds them in your terminal only (all in
             /home/demo/.nvm/versions/node/v22.4.0/bin).
      found  ~/.bashrc:7: export NVM_DIR="$HOME/.nvm"  (below the interactive-only guard at line 2)
      found  ~/.bashrc:8: export PATH="$HOME/.nvm/versions/node/v22.4.0/bin:$HOME/.local/bin:$PATH"
             (below the interactive-only guard at line 2)
      fix    nvm is a shell function loaded from nvm.sh; agents never load it, so only the resolved bin
             directory can be pinned. Re-pin after `nvm use`/`nvm alias default`.
             Add to ~/.bash_env:
                 export PATH="$HOME/.nvm/versions/node/v22.4.0/bin:$PATH"

 ✖ ERROR  #2 the agent shell is not UTF-8
      human  LANG=C.UTF-8; charmap=UTF-8; UTF-8 ok
      agent  LANG=C; charmap=ANSI_X3.4-1968; NOT UTF-8
      why    Non-ASCII text (Persian, emoji, accents) in file names, git output and tool output can be
             mangled or fail with encoding errors.
      found  ~/.bashrc:13: export LANG=C.UTF-8  (below the interactive-only guard at line 2)
      fix    Add to ~/.bash_env:
                 export LANG=C.UTF-8
```

*Excerpt of `shellparity --demo scripted` (unedited lines). The full output of a real run against a fake home is in [docs/demo.txt](docs/demo.txt).*

## The problem

AI coding agents and other automation run commands in a **non-login, non-interactive shell**
(or something close to it). That shell does not read `~/.zshrc` or `~/.bashrc`, so everything
you configured there is invisible:

- `nvm` / `pyenv` / `asdf` / `fnm` versions → `command not found`, or the *system* Node 12 instead of your Node 22
- `HTTPS_PROXY` and friends → `npm install` and `git clone` hang or time out
- `LANG` / `LC_ALL` → Persian, emoji and accented text come out as `?` or crash a tool
- `SSH_AUTH_SOCK` → `git push` over SSH fails or waits for a passphrase nobody can type
- API keys exported in your rc file → the agent's scripts cannot call the API
- `commit.gpgsign=true` without a TTY → `git commit` fails with "gpg failed to sign the data"

The manual diagnosis is well known (`zsh -c` vs `zsh -i -c`, see for example
[cline#5824](https://github.com/cline/cline/issues/5824),
[openworker#362](https://github.com/andrewyng/openworker/issues/362) and
[this write-up](https://layer5.io/blog/engineering/why-claude-code-cant-find-your-tools)),
but you end up diffing `env` output by hand and guessing which dotfile to edit.
`shellparity` automates exactly that, on the same machine, and prints the file and the lines.

## Install

Python 3.9 or newer on Linux or macOS. No dependencies.

```sh
# from GitHub (isolated, recommended)
pipx install git+https://github.com/mrzroot/shellparity
# or
uv tool install git+https://github.com/mrzroot/shellparity

# or run without installing, from a clone
git clone https://github.com/mrzroot/shellparity && cd shellparity
python -m shellparity
```

It is not on PyPI yet (the name was free as of Oct 2026).

## Usage

```sh
shellparity                       # your $SHELL: terminal vs `<shell> -c`
shellparity --shell all           # every bash/zsh/sh found on this machine
shellparity --agent-mode login    # the agent runs `<shell> -lc` instead
shellparity --project ~/code/app  # also check .nvmrc / package.json / pyproject.toml of a project
shellparity --tool terraform      # also compare another command
shellparity --json                # machine-readable, with every finding and its fix
shellparity --markdown > AGENT_ENV.md   # paste-ready notes for your agent's context file
shellparity --write-snippet ~/.bash_env.draft   # write the suggested export lines (review first!)
shellparity --fail-on error       # exit 1 if there is an error: use as a hook or in CI
shellparity --demo                # offline demo with a fake home directory (nothing of yours is read)
```

| Option | Meaning |
| --- | --- |
| `--shell NAME\|PATH\|all` | `bash`, `zsh`, `sh`, a path, or `all`. Default: `$SHELL`, else the first one found. |
| `--agent-mode` | How the agent's shell is started: `plain` (default, `-c`), `login`, `interactive`, `bare`. |
| `--json` / `--markdown` | Alternative reports. |
| `--write-snippet FILE` | The only way shellparity writes a file, and only the one you name. |
| `--fail-on error\|warn\|info` | Exit status 1 if a finding of at least this severity exists. 2 means a probe failed. |
| `--demo [live\|scripted]` | `live`: real bash against a temporary fake `HOME`. `scripted`: hand-written snapshots, no shell started. |
| `--project DIR`, `--tool NAME` | Add project version requirements or extra commands to compare. |
| `--inherit-env` | Start every probed shell from *this* process's environment instead of a clean one. |
| `--timeout SEC` | Per-mode timeout (default 30 s). |
| `--no-color`, `-v` | Plain output (also `NO_COLOR=1`), probe diagnostics. |

## What it checks

Only things that are implemented and covered by tests are listed here.

| Area | What is compared | Severity logic |
| --- | --- | --- |
| **PATH** | Directories present in the human shell but missing for the agent | warn |
| **Tools** | 27 common commands (`node npm npx pnpm yarn bun deno python python3 pip pip3 uv pipx git gh go rustc cargo java mvn docker make gcc curl wget ssh jq`) plus any `--tool`: resolved path and `--version` | error if missing for the agent, if it resolves to a different *major* version of node/python/go/java/rustc/npm/pnpm, or if it is found but fails to run; warn for other version differences, aliases; note for same version at a different path |
| **Project** | `.nvmrc`, `.node-version`, `.python-version`, `.tool-versions`, `package.json` `engines.node`, `pyproject.toml` `requires-python` against the agent's node/python (major, or major.minor for Python) | error if your shell satisfies it and the agent's does not, else warn |
| **Proxy** | `http_proxy`/`https_proxy`/`all_proxy`/`no_proxy` in both spellings: set only in one shell, different values, only one spelling set, `NO_PROXY` without localhost. Credentials in URLs are masked. | warn / note |
| **Locale** | `LANG`, `LC_*`, `locale charmap`, and a **real test**: the shell counts the characters of a Persian word (4 characters, 8 bytes). A byte count means the shell is not UTF-8, even if `LANG` claims otherwise (locale not installed, `LC_ALL=C` override). | error if the agent is not UTF-8 and yours is |
| **SSH** | `SSH_AUTH_SOCK` set and a real socket in your shell, missing in the agent's | warn |
| **git** | Effective `user.*`, `commit.gpgsign`, `gpg.format`, `credential.helper`, `core.sshCommand` per shell; signing enabled but no TTY and no `GPG_TTY`; SSH signing without an agent | warn / note |
| **Environment** | Allow-listed variables (runtime managers, `JAVA_HOME`, `GOPATH`, `VIRTUAL_ENV`, `NODE_OPTIONS`, `PIP_INDEX_URL`, `EDITOR`, ...) by value; every other exported variable by **name only** | warn for runtime variables, note otherwise |
| **Secrets** | Variable *names* that look like secrets (`*TOKEN*`, `*API_KEY*`, `*PASSWORD*`, `*_KEY`, ...) that exist only in your shell. Values are never read. | warn |
| **TTY / TERM** | stdin is a TTY for you but not for the agent; `TERM` unset or `dumb` | note |
| **Misc** | alias count, `umask`, `ulimit -n`, timezone abbreviation | note |
| **Startup files** | Which files exist and which mode reads them; early `return` guards in `~/.bashrc` that make everything below them invisible when sourced non-interactively | informational |

Not detected in v0.1: version managers' *own* selection logic beyond what the shells resolve
(for example `nvm use` in a per-directory hook), `direnv` hooks, `fish`, PowerShell, Windows,
shell functions (only counted as "not a binary"), GUI-launched environments (launchd, systemd user
units), and anything a specific agent product does to the environment it passes to its shell.

## How it works

1. **Probe.** One POSIX `sh` script (`shellparity/probe.py`) is written to a temp directory and
   *sourced* by each shell. It writes `SP<TAB>key<TAB>value` records to a temp file, so banners and
   prompts from your rc files cannot corrupt the result. It only reads: `command -v`, `--version`
   (with `timeout 8` when available, stdin from `/dev/null`), `git config --get`, `alias`, `umask`,
   and a fixed list of non-secret variable names.
2. **Modes.** Each mode is a fresh child process:

   | mode | command | tty |
   | --- | --- | --- |
   | `human` | `<shell> -l -i -c ...` | pseudo-terminal, like a terminal emulator |
   | `login` | `<shell> -l -c ...` | no |
   | `interactive` | `<shell> -i -c ...` | no |
   | `plain` | `<shell> -c ...` | no |
   | `bare` | `env -i HOME=... <shell> -c ...` | no |

   By default every shell starts from a **clean, login-like environment**: `HOME`, `USER`, `LOGNAME`,
   `LANG`, `LANGUAGE`, `TZ` copied from you and `PATH=/usr/bin:/bin`. The question answered is
   "what do the startup files provide?". Use `--inherit-env` to start from your current
   environment instead (closer to an agent launched from this terminal).
3. **Compare.** `compare(human, agent)` in `shellparity/compare.py` is a pure function: two
   snapshots in, ranked findings out. No processes, no files.
4. **Advise.** For each finding the other modes are checked ("a login shell already sees this"),
   your rc files are searched textually (`export NAME=`, PATH entries, version-manager markers, one
   level of `source`/`.`) so the report can say `~/.zshrc:14`, and a fix is printed for the
   right file: `~/.zshenv` for zsh (read by every invocation), a file named by `$BASH_ENV` for
   non-interactive bash, `~/.bash_profile`/`~/.profile` for login bash, and for plain `sh` the honest
   answer that nothing is read.

**Privacy and safety.** shellparity never edits your files. Your rc files *do* run, because that is the
point (so a slow `nvm` makes it slow, and an rc file that starts `ssh-agent` will start one). Secret
values are never read: the probe asks for allow-listed non-secret variables only and lists all other
variables by name. URLs have credentials masked, and lines quoted from your rc files have secret-named
assignments redacted. The tests assert this end to end.

## Limits (please read)

- **Linux and macOS, bash, zsh and sh only.** No fish, PowerShell or native Windows (use WSL). CI runs
  on Ubuntu; the macOS job is informational and the author has not been able to run it on a Mac yet.
- **"The agent shell" is a model.** Agents differ: some run `bash -c`, some a login shell, some
  snapshot your shell's environment at start, some inherit the environment of the app that launched
  them. shellparity cannot know which. Pick the closest `--agent-mode`, read the mode matrix, and treat
  the result as "this is what the startup files provide in that mode", not a trace of one specific product.
- **Rc-file lookup is textual.** It does not evaluate your dotfiles, so a matching line may sit in a branch that
  did not run, `ZDOTDIR` is not followed, and definitions built dynamically are not found (the finding
  is still reported, only the `found` line is missing).
- **Interactive rc files can hang or prompt** (update checks, first-run wizards). Each mode has a
  timeout and a failed probe is reported as such. The only prompt answered automatically is zsh's
  first-run wizard (answer `q`, nothing is written).
- **Version checks are coarse.** Major version for Node, major.minor for Python, a subset of semver/PEP 440.
- **git and ssh checks are configuration-level.** shellparity does not run `gpg` or contact an ssh-agent.
- **Suggested fixes are printed, not applied,** and are a starting point: pinning an `nvm` directory
  freezes that version until you re-pin.

## How it differs from existing tools

*No existing tool found as of Oct 2026* that compares one machine's interactive and non-interactive
shells across PATH, tool versions, proxy, locale, SSH and git and prints the fix. That statement comes
from searches of GitHub, npm, PyPI and the web on 2026-10-18; search indexes are incomplete and this
space changes weekly. If you know one, [open an issue](https://github.com/mrzroot/shellparity/issues)
and it will be linked here.

| Tool | What it does | How shellparity differs |
| --- | --- | --- |
| [`shell-drift-check.ts` gist](https://gist.github.com/erukiti/f6caafc6224359a634326c890a34fdc5) | Compares `bash -lc` vs `zsh -lc`: PATH order, resolution, versions, alias names | One script, human-zsh vs agent-bash only; no proxy/locale/SSH/git/TTY checks, no fix output, not packaged |
| [`becky-exists/agent-environment-doctor`](https://github.com/becky-exists/agent-environment-doctor) | Diagnoses which skills/rules load in Claude Code/Codex | About agent configuration, not the shell environment |
| [`thecatnamedkuro/agent-env-doctor`](https://github.com/thecatnamedkuro/agent-env-doctor) | Repo-readiness preflight (lockfiles, `.env.example`, runbook docs) | Checks whether commands exist in the *current* shell only |
| [`player1-mm/env-drift-detector`](https://github.com/player1-mm/env-drift-detector) | Drift between machines or teammates against a stored snapshot | Different problem: this is *same machine, different shell mode* |
| [`mise`](https://mise.jdx.dev), [`direnv`](https://direnv.net), [`asdf`](https://asdf-vm.com) | *Select* tool versions per project | They fix version selection; they do not diagnose what a given shell mode sees. shellparity tells you when you need their shims on `PATH` |
| Manual `zsh -c` vs `zsh -i -c` | Works, but you diff `env` by eye | This automates it, adds the checks above, and names the file to edit |

## Using it with agents

- Paste [`docs/AGENTS.snippet.md`](docs/AGENTS.snippet.md) into your `AGENTS.md` / `CLAUDE.md`, so the agent runs `shellparity --markdown` when a command is missing or wrong, and *asks you* before touching dotfiles.
- Or generate `AGENT_ENV.md` once: `shellparity --markdown > AGENT_ENV.md`.
- In a hook or CI: `shellparity --fail-on error` (exit 1) is a cheap guard that your agent environment still matches what you tested.

## Development

```sh
pip install -e '.[test]'
pytest            # ~110 tests; real bash/zsh/sh runs use a fake HOME in tmp_path
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CHANGELOG.md](CHANGELOG.md).

## License

MIT © 2026 Mohammadreza Zare ([@mrzroot](https://github.com/mrzroot))
