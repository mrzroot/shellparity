"""The probe: one POSIX sh script that every shell mode runs.

The script writes tab-separated records (``SP<TAB>key<TAB>value``) to the file
named by ``$SP_OUT``. Writing to a file (instead of stdout) means rc-file noise
such as banners, prompts and escape sequences can never corrupt the result.

Secrets: the probe only reads the *values* of the allow-listed, non-secret
variable names in ``KEY_VARS``. For every other variable it records the name
only (via ``env``), never the value.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

# Common tools whose resolution and version are compared.
TOOLS: List[str] = [
    "node", "npm", "npx", "pnpm", "yarn", "bun", "deno",
    "python", "python3", "pip", "pip3", "uv", "pipx",
    "git", "gh", "go", "rustc", "cargo",
    "java", "mvn", "docker", "make", "gcc",
    "curl", "wget", "ssh", "jq",
]

# Non-secret variables whose values are read. Grouped for the comparison rules.
PROXY_VARS = ["http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY",
              "all_proxy", "ALL_PROXY", "no_proxy", "NO_PROXY"]
LOCALE_VARS = ["LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "LC_MESSAGES"]
TERM_VARS = ["TERM", "COLUMNS", "LINES", "COLORTERM", "NO_COLOR"]
SSH_GPG_VARS = ["SSH_AUTH_SOCK", "SSH_ASKPASS", "GIT_SSH_COMMAND", "GPG_TTY", "GNUPGHOME"]
EDITOR_VARS = ["EDITOR", "VISUAL", "PAGER", "GIT_PAGER", "BROWSER"]
RUNTIME_VARS = [
    "NVM_DIR", "NVM_BIN", "PNPM_HOME", "VOLTA_HOME", "FNM_DIR", "PYENV_ROOT",
    "PYENV_VERSION", "VIRTUAL_ENV", "CONDA_PREFIX", "CONDA_DEFAULT_ENV",
    "ASDF_DIR", "ASDF_DATA_DIR", "MISE_DATA_DIR", "GOPATH", "GOROOT", "GOFLAGS",
    "GOPROXY", "CARGO_HOME", "RUSTUP_HOME", "JAVA_HOME", "SDKMAN_DIR",
    "RBENV_ROOT", "NODE_OPTIONS", "NODE_PATH", "NODE_EXTRA_CA_CERTS",
    "PYTHONPATH", "PYTHONUTF8", "PYTHONIOENCODING", "PIP_INDEX_URL",
    "NPM_CONFIG_REGISTRY", "UV_INDEX_URL",
]
MISC_VARS = ["TZ", "CI", "SHELL", "HOME", "USER", "LOGNAME", "XDG_CONFIG_HOME",
             "GIT_CONFIG_GLOBAL", "BASH_ENV", "ENV", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE",
             "CURL_CA_BUNDLE", "HF_ENDPOINT"]

KEY_VARS: List[str] = (PROXY_VARS + LOCALE_VARS + TERM_VARS + SSH_GPG_VARS
                       + EDITOR_VARS + RUNTIME_VARS + MISC_VARS)

GIT_KEYS = ["user.name", "user.email", "user.signingkey", "commit.gpgsign",
            "tag.gpgsign", "gpg.format", "gpg.program", "credential.helper",
            "core.sshCommand", "core.editor"]

PERSIAN_PROBE = "\u0633\u0644\u0627\u0645"  # "salam": 4 characters, 8 bytes in UTF-8

_TEMPLATE = r'''# shellparity probe v1 (POSIX sh) - read-only; writes records to $SP_OUT
sp_tty0=0; [ -t 0 ] && sp_tty0=1
sp_tty1=0; [ -t 1 ] && sp_tty1=1
sp_tty2=0; [ -t 2 ] && sp_tty2=1
sp_flags=$-
[ -n "$SP_OUT" ] || exit 3

sp_put() {
  sp_pv=$(command printf '%s' "$2" | command tr '\n\t\r' '   ')
  command printf 'SP\t%s\t%s\n' "$1" "$sp_pv" >> "$SP_OUT"
}

sp_run() {
  # $1=tool name, $2=resolved path. stdin is /dev/null; use timeout(1) when present.
  case "$1" in
    go) sp_a=version ;;
    ssh) sp_a=-V ;;
    java) sp_a=-version ;;
    *) sp_a=--version ;;
  esac
  if command -v timeout >/dev/null 2>&1; then
    command timeout 8 "$2" "$sp_a" 2>&1 </dev/null
  else
    "$2" "$sp_a" 2>&1 </dev/null
  fi
}

sp_put tty0 "$sp_tty0"
sp_put tty1 "$sp_tty1"
sp_put tty2 "$sp_tty2"
sp_put flags "$sp_flags"
sp_put shellver "${BASH_VERSION:-${ZSH_VERSION:-}}"
sp_put path "$PATH"

for sp_t in @@TOOLS@@; do
  sp_w=$(command -v "$sp_t" 2>/dev/null)
  if [ -z "$sp_w" ]; then continue; fi
  sp_put "tool:${sp_t}:where" "$sp_w"
  case "$sp_w" in
    /*)
      sp_vv=$(sp_run "$sp_t" "$sp_w"); sp_rc=$?
      sp_first=$(command printf '%s\n' "$sp_vv" | command head -n 1)
      sp_put "tool:${sp_t}:rc" "$sp_rc"
      sp_put "tool:${sp_t}:ver" "$sp_first"
      ;;
  esac
done

for sp_n in @@VARS@@; do
  eval "sp_isset=\${$sp_n+set}"
  if [ "$sp_isset" = set ]; then
    eval "sp_val=\$$sp_n"
    sp_put "var:$sp_n" "$sp_val"
  fi
done

sp_names=$(command env 2>/dev/null | command sed -n 's/^\([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p' | command tr '\n' ' ')
sp_put envnames "$sp_names"

if [ -n "$SSH_AUTH_SOCK" ]; then
  if [ -S "$SSH_AUTH_SOCK" ]; then sp_put ssh_sock_ok 1; else sp_put ssh_sock_ok 0; fi
fi

sp_cm=$(command locale charmap 2>/dev/null)
sp_put charmap "$sp_cm"
sp_nc=$(command printf '%s' '@@PERSIAN@@' | command wc -m | command tr -d ' ')
sp_put persian_chars "$sp_nc"

if command -v git >/dev/null 2>&1; then
  for sp_k in @@GITKEYS@@; do
    sp_gv=$(cd / && command git config --get "$sp_k" 2>/dev/null)
    [ -n "$sp_gv" ] && sp_put "git:$sp_k" "$sp_gv"
  done
fi

sp_al=$(alias 2>/dev/null | command wc -l | command tr -d ' ')
sp_put aliases "$sp_al"
sp_put umask "$(umask)"
sp_put ulimit_n "$(ulimit -n 2>/dev/null)"
sp_put tz_abbr "$(command date +%Z 2>/dev/null)"
sp_put done 1
'''


def build_probe(extra_tools: Optional[Sequence[str]] = None,
                only_tools: Optional[Sequence[str]] = None) -> str:
    """Return the probe script text. ``extra_tools`` are added to the tool list;
    ``only_tools`` replaces it (used by the demo)."""
    tools = list(only_tools) if only_tools else list(TOOLS)
    for t in extra_tools or []:
        if t and t not in tools and all(c.isalnum() or c in "-_." for c in t):
            tools.append(t)
    return (_TEMPLATE
            .replace("@@TOOLS@@", " ".join(tools))
            .replace("@@VARS@@", " ".join(KEY_VARS))
            .replace("@@GITKEYS@@", " ".join(GIT_KEYS))
            .replace("@@PERSIAN@@", PERSIAN_PROBE))


def tool_names(extra_tools: Optional[Sequence[str]] = None) -> Dict[str, None]:
    d: Dict[str, None] = {t: None for t in TOOLS}
    for t in extra_tools or []:
        d.setdefault(t, None)
    return d
