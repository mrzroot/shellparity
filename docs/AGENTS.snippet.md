<!-- Paste into your project's AGENTS.md / CLAUDE.md / rules file. -->

## Shell environment

Commands you run in this repository execute in a non-interactive shell, which does **not**
read the developer's interactive startup files (`~/.zshrc`, `~/.bashrc`). Tools installed by
nvm/pyenv/asdf, proxy variables, `LANG`, `SSH_AUTH_SOCK` and API keys may therefore be missing
or different from what the developer sees in their terminal.

If a command is "not found", picks the wrong Node/Python version, cannot reach the network, or
prints garbled non-ASCII text, run this first and read its findings:

    shellparity --markdown

(or `shellparity --json`, which lists every finding with its fix.) Do **not** edit the
developer's rc files yourself. Quote the suggested fix in your reply and ask them to apply it.
Until it is fixed, use absolute paths or an explicit `export PATH=...` in your own command.
