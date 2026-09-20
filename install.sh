#!/bin/zsh
# claude-worksessions installer. Safe to re-run: every step checks before it acts,
# and anything it replaces is backed up first.
#
#   ./install.sh                      install / update using your config
#   ./install.sh --config FILE        use this config.env
#   ./install.sh --dry-run            print what would change, change nothing
#   ./install.sh --no-brew            don't install Homebrew packages
#   ./install.sh --no-bootstrap       don't install anything missing, just report it
#   ./install.sh --yes                don't prompt (tokens are then skipped)

emulate -L zsh
setopt pipe_fail

REPO="${0:A:h}"
VERSION="$(<"$REPO/VERSION")"
DRY=0 BREW=1 YES=0 NOBOOT=0 CONFIG=""
STAMP="$(date +%Y%m%d-%H%M%S)"

while (( $# )); do
  case "$1" in
    --config)  CONFIG="${2:A}"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    --no-brew) BREW=0; shift ;;
    --no-bootstrap) NOBOOT=1; BREW=0; shift ;;
    --yes|-y)  YES=1; shift ;;
    -h|--help) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) print -u2 "install.sh: unknown option $1"; exit 1 ;;
  esac
done

say()  { print -r -- "  $*"; }
step() { print -r -- ""; print -r -- "▸ $*"; }
warn() { print -u2 -r -- "  ! $*"; }
run()  { if (( DRY )); then print -r -- "    [dry-run] $*"; else "$@"; fi; }

# Back up a file or directory we are about to replace (not symlinks we own)
backup() {
  local f="$1"
  [[ -e "$f" && ! -L "$f" ]] || return 0
  run cp -Rp "$f" "$f.bak-$STAMP"
  say "backed up $f → ${f:t}.bak-$STAMP"
}

# Render a {{KEY}} template with the config (and HOME) to a file, backing up a changed target
render() {
  local src="$1" dst="$2" tmp
  tmp="$(mktemp)"
  "$PY" - "$src" "$tmp" <<'PY'
import os, re, sys
src, dst = sys.argv[1], sys.argv[2]
text = open(src).read()
env = dict(os.environ)
def sub(m):
    key = m.group(1)
    if key not in env:
        sys.exit("render: {} has no value for {{{{{}}}}}".format(src, key))
    return env[key]
open(dst, "w").write(re.sub(r"\{\{([A-Z_]+)\}\}", sub, text))
PY
  if [[ -f "$dst" ]] && cmp -s "$tmp" "$dst"; then
    say "unchanged $dst"; rm -f "$tmp"; return 0
  fi
  [[ -f "$dst" ]] && backup "$dst"
  run mkdir -p "${dst:h}"
  if (( DRY )); then print -r -- "    [dry-run] write $dst"; rm -f "$tmp"; else mv "$tmp" "$dst"; say "wrote $dst"; fi
}

# Symlink dst → src unless it already points there
link() {
  local src="$1" dst="$2"
  if [[ -L "$dst" && "$(readlink "$dst")" == "$src" ]]; then say "ok $dst"; return 0; fi
  if [[ -e "$dst" || -L "$dst" ]]; then
    backup "$dst"
    run rm -rf "$dst"
  fi
  run mkdir -p "${dst:h}"
  run ln -s "$src" "$dst"
  say "linked $dst → $src"
}

print -r -- "claude-worksessions $VERSION"

# --- 1. config -----------------------------------------------------------------------
step "Configuration"
LINK="$HOME/.config/claude-worksessions/config.env"
if [[ -z "$CONFIG" && -e "$LINK" ]]; then CONFIG="${LINK:A}"; fi
if [[ -z "$CONFIG" ]]; then
  local root_default="$HOME/work_sessions" root
  if (( YES )); then root="$root_default"
  else read "root?Work root (where request folders live) [$root_default]: "; root="${root:-$root_default}"; fi
  root="${~root}"
  CONFIG="$root/_config/config.env"
  if [[ ! -f "$CONFIG" ]]; then
    run mkdir -p "${CONFIG:h}"
    if (( ! DRY )); then
      sed "s|^CWS_WORK_ROOT=.*|CWS_WORK_ROOT=\"${root/#$HOME/\$HOME}\"|" "$REPO/config/config.example.env" > "$CONFIG"
    fi
    say "created $CONFIG from the example."
    say "Edit it (org, time zone, profiles, gateway URL) and run ./install.sh again."
    exit 0
  fi
fi
[[ -f "$CONFIG" ]] || { print -u2 "install.sh: config $CONFIG not found"; exit 1; }
say "using $CONFIG"
[[ "$CONFIG" == "${LINK:A}" ]] || link "$CONFIG" "$LINK"

# Load it exactly as the shell functions will
export CWS_CONFIG="$CONFIG"
source "$REPO/shell/worksessions.zsh"
unalias -m 'claude-*' 2>/dev/null || true
typeset -a PROFILES=(${=CWS_PROFILES})
: ${CWS_SHARED_PROFILE:=${PROFILES[1]}}
: ${CWS_ORG:=} ${CWS_USER_ROLE:=} ${CWS_TIMEZONE:=UTC} ${CWS_TIMEZONE_WINDOWS:=UTC} ${CWS_JIRA_CLOUD_ID:=} ${CWS_INSTALL_YAZI:=1}
export HOME CWS_WORK_ROOT="$CLAUDE_WORK_ROOT" CWS_ORG CWS_USER_ROLE CWS_TIMEZONE CWS_TIMEZONE_WINDOWS \
       CWS_TICKET_EXAMPLE CWS_JIRA_CLOUD_ID
say "work root  $CWS_WORK_ROOT"
say "profiles   ${PROFILES[*]} (default $CWS_DEFAULT_PROFILE, shared $CWS_SHARED_PROFILE)"

# --- 2. prerequisites --------------------------------------------------------------------
# Nothing here is assumed to be present: a clean Mac gets the Command Line Tools,
# Homebrew, Claude Code and the packages, after one confirmation.
step "Prerequisites"

brew_path() { [[ -x /opt/homebrew/bin/brew ]] && print -r -- /opt/homebrew/bin/brew ||
              { [[ -x /usr/local/bin/brew ]] && print -r -- /usr/local/bin/brew; } }
have_clt()  { /usr/bin/xcode-select -p >/dev/null 2>&1 }
have_brew() { command -v brew >/dev/null 2>&1 || [[ -n "$(brew_path)" ]] }

typeset -a want=(fzf)
(( CWS_INSTALL_YAZI )) && want+=(yazi glow pandoc)
typeset -a pkgs_missing=() plan=()
local pkg
for pkg in $want; do command -v $pkg >/dev/null 2>&1 || pkgs_missing+=($pkg); done

have_clt  || plan+=("Xcode Command Line Tools (git, compilers — opens Apple's installer)")
have_brew || plan+=("Homebrew (https://brew.sh — may ask for your admin password)")
command -v claude >/dev/null 2>&1 || plan+=("Claude Code (claude)")
(( ${#pkgs_missing} )) && plan+=("Homebrew packages: ${pkgs_missing[*]}")

if (( ! ${#plan} )); then
  say "all present: Command Line Tools, Homebrew, Claude Code, ${want[*]}"
else
  print -r -- "  This Mac is missing:"
  local it
  for it in $plan; do print -r -- "    · $it"; done
  local ans="y"
  if (( DRY )); then say "[dry-run] would install the above"; ans="n"
  elif (( ! YES && ! NOBOOT )); then read "ans?  Install them now? [Y/n]: "; ans="${ans:-y}"
  elif (( NOBOOT )); then ans="n"; fi

  if [[ "${ans:l}" == y* ]]; then
    if ! have_clt; then
      say "asking macOS for the Command Line Tools…"
      /usr/bin/xcode-select --install 2>/dev/null || true
      say "finish the dialog that just opened; waiting…"
      local waited=0
      while ! have_clt && (( waited < 1800 )); do sleep 10; (( waited += 10 )); done
      have_clt && say "Command Line Tools ready" || warn "still not installed — rerun install.sh afterwards"
    fi
    if ! have_brew; then
      say "installing Homebrew…"
      NONINTERACTIVE=1 /bin/bash -c \
        "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" || \
        warn "Homebrew install failed — see https://brew.sh"
    fi
    local BREW_BIN="$(brew_path)"
    if [[ -n "$BREW_BIN" ]]; then
      eval "$("$BREW_BIN" shellenv)"
      # Homebrew's own PATH line belongs in ~/.zprofile, where its installer puts it
      if ! grep -qs 'brew shellenv' "$HOME/.zprofile"; then
        print -r -- "eval \"\$($BREW_BIN shellenv)\"" >> "$HOME/.zprofile"
        say "added brew shellenv to ~/.zprofile"
      fi
    fi
    if ! command -v claude >/dev/null 2>&1; then
      say "installing Claude Code…"
      curl -fsSL https://claude.ai/install.sh | bash || warn "Claude Code install failed — see https://docs.claude.com/claude-code"
      export PATH="$HOME/.local/bin:$PATH"
    fi
    if (( ${#pkgs_missing} )) && (( BREW )) && command -v brew >/dev/null 2>&1; then
      brew install $pkgs_missing || warn "brew install failed for: ${pkgs_missing[*]}"
    fi
  else
    warn "skipped — install by hand, then run ./install.sh again"
  fi
fi

# Python for the JSON helpers: the system one, else Homebrew's, else install it
PY=""
if [[ -x /usr/bin/python3 ]]; then PY=/usr/bin/python3
elif command -v python3 >/dev/null 2>&1; then PY="$(command -v python3)"
elif command -v brew >/dev/null 2>&1 && (( ! DRY )); then
  say "installing python…"; brew install python >/dev/null && PY="$(command -v python3)"
fi
[[ -n "$PY" ]] || { print -u2 "install.sh: no python3 — install the Command Line Tools or run: brew install python"; exit 1; }
export CWS_PYTHON="$PY"
say "python     $PY"
command -v claude >/dev/null 2>&1 && say "claude     $(claude --version 2>/dev/null | head -1)" \
  || warn "Claude Code is still not on PATH"

# --- 3. work root ----------------------------------------------------------------------
step "Work root"
local d
for d in "$CWS_WORK_ROOT" "$CWS_WORK_ROOT/_audit" "$CWS_WORK_ROOT/_config" "$CWS_WORK_ROOT/_daily"; do
  [[ -d "$d" ]] || { run mkdir -p "$d"; say "created $d"; }
done
local name
for name in context review-rules; do
  if [[ -f "$CWS_WORK_ROOT/_config/$name.md" ]]; then say "kept _config/$name.md"
  else run cp "$REPO/config/$name.example.md" "$CWS_WORK_ROOT/_config/$name.md"; say "created _config/$name.md — fill it in"; fi
done
render "$REPO/templates/CLAUDE.md.tmpl" "$CWS_WORK_ROOT/CLAUDE.md"

# --- 4. Claude Code profiles ----------------------------------------------------------
step "Claude Code profiles"
SHARED="$HOME/.claude-$CWS_SHARED_PROFILE"
typeset -a SHARED_ITEMS=(projects sessions session-env history.jsonl file-history shell-snapshots skills plugins mcp)
[[ -d "$SHARED" ]] || { run mkdir -p "$SHARED"; say "created $SHARED"; }
local item p pdir
for item in $SHARED_ITEMS; do
  if [[ ! -e "$SHARED/$item" ]]; then
    if [[ "$item" == *.jsonl ]]; then run touch "$SHARED/$item"; else run mkdir -p "$SHARED/$item"; fi
  fi
done
for p in $PROFILES; do
  pdir="$HOME/.claude-$p"
  [[ -d "$pdir" ]] || { run mkdir -p "$pdir"; say "created $pdir"; }
  if [[ "$p" != "$CWS_SHARED_PROFILE" ]]; then
    for item in $SHARED_ITEMS; do
      if [[ -L "$pdir/$item" && "$(readlink "$pdir/$item")" == "$SHARED/$item" ]]; then continue; fi
      if [[ -e "$pdir/$item" && ! -L "$pdir/$item" ]]; then
        warn "$pdir/$item is a real file/dir, not shared — left alone (merge it into $SHARED/$item, then re-run)"
        continue
      fi
      link "$SHARED/$item" "$pdir/$item"
    done
  fi
  # Optional API gateway for this profile
  local urlvar="CWS_PROFILE_${p}_BASE_URL"
  local url="${(P)urlvar:-}"
  if [[ -n "$url" ]]; then
    local settings="$pdir/settings.json" has_token token=""
    has_token=$("$PY" -c 'import json,sys
try: print(1 if json.load(open(sys.argv[1])).get("env",{}).get("ANTHROPIC_AUTH_TOKEN") else 0)
except Exception: print(0)' "$settings")
    if (( ! has_token && ! YES && ! DRY )); then
      read -s "token?  Token for the $p profile's gateway ($url), Enter to skip: "; print
    fi
    if (( DRY )); then say "[dry-run] set ANTHROPIC_BASE_URL in $settings"
    else
      TOKEN="$token" URL="$url" "$PY" - "$settings" <<'PY'
import json, os, sys
p = sys.argv[1]
try: d = json.load(open(p))
except Exception: d = {}
env = d.setdefault("env", {})
env["ANTHROPIC_BASE_URL"] = os.environ["URL"]
if os.environ.get("TOKEN"): env["ANTHROPIC_AUTH_TOKEN"] = os.environ["TOKEN"]
json.dump(d, open(p, "w"), indent=2)
os.chmod(p, 0o600)
PY
      say "$p: gateway $url${token:+ (token saved)}"
      (( has_token || ${#token} )) || warn "$p: no token set — re-run install.sh to add one"
    fi
  fi
done
if [[ ! -e "$HOME/.claude" ]]; then link ".claude-$CWS_SHARED_PROFILE" "$HOME/.claude"
else say "kept ~/.claude"; fi

# --- 4b. sign in -----------------------------------------------------------------------
# Each config dir has its own login, and there is no documented way to ask Claude Code
# whether one is signed in, so we offer to open each profile once and note that we did.
step "Sign in"
for p in $PROFILES; do
  pdir="$HOME/.claude-$p"
  local urlvar2="CWS_PROFILE_${p}_BASE_URL" marker="$pdir/.cws-signed-in"
  if [[ -n "${(P)urlvar2:-}" ]]; then
    say "$p: uses the gateway token — no login needed"
    continue
  fi
  if [[ -f "$marker" ]]; then say "$p: signed in earlier (delete $marker to redo)"; continue; fi
  if (( DRY )); then say "[dry-run] would offer to sign in to $p"; continue; fi
  if (( YES )) || ! command -v claude >/dev/null 2>&1; then
    warn "$p: not signed in yet — run: CLAUDE_CONFIG_DIR=$pdir claude"
    continue
  fi
  local ans2=""
  read "ans2?  Open Claude now to sign in to the '$p' profile? [Y/n]: "
  if [[ "${${ans2:-y}:l}" == y* ]]; then
    say "starting Claude — sign in if asked, then type /exit to come back"
    CLAUDE_CONFIG_DIR="$pdir" command claude || true
    touch "$marker"
    say "$p: done"
  else
    warn "$p: skipped — run later: CLAUDE_CONFIG_DIR=$pdir claude"
  fi
done

# --- 5. commands and skills -----------------------------------------------------------
step "Commands"
local b
for b in claude-audit claude-search; do link "$REPO/bin/$b" "$HOME/.local/bin/$b"; done

step "Skills"
local s
for s in "$REPO"/skills/*(/); do
  render "$s/SKILL.md" "$SHARED/skills/${s:t}/SKILL.md"
done

# --- 6. yazi ------------------------------------------------------------------------------
if (( CWS_INSTALL_YAZI )); then
  step "yazi"
  local Y="$HOME/.config/yazi" f
  render "$REPO/yazi/yazi.toml.tmpl" "$Y/yazi.toml"
  for f in glow-style.json glow-style-light.json md-email.css md2html.sh; do
    if [[ -f "$Y/$f" ]] && cmp -s "$REPO/yazi/$f" "$Y/$f"; then say "unchanged $Y/$f"; continue; fi
    [[ -f "$Y/$f" ]] && backup "$Y/$f"
    run mkdir -p "$Y"; run cp "$REPO/yazi/$f" "$Y/$f"; say "wrote $Y/$f"
  done
  run chmod +x "$Y/md2html.sh"
  if [[ -d "$Y/plugins/piper.yazi" ]]; then say "ok piper plugin"
  elif command -v ya >/dev/null; then run ya pkg add yazi-rs/plugins:piper
  else warn "yazi not installed — skipped the piper plugin"; fi
fi

# --- 7. ~/.zshrc -----------------------------------------------------------------------
step "~/.zshrc"
ZSHRC="$HOME/.zshrc"
BEGIN="# >>> claude-worksessions >>>"
END="# <<< claude-worksessions <<<"
BLOCK="$BEGIN
# Managed by $REPO/install.sh — edit the config, not this block.
export PATH=\"\$HOME/.local/bin:\$PATH\"
source \"$REPO/shell/worksessions.zsh\"
$END"
[[ -f "$ZSHRC" ]] || run touch "$ZSHRC"
if [[ -f "$ZSHRC" ]] && grep -qF "$BEGIN" "$ZSHRC"; then
  current="$(awk -v b="$BEGIN" -v e="$END" '$0==b{f=1} f{print} $0==e{f=0}' "$ZSHRC")"
  if [[ "$current" == "$BLOCK" ]]; then say "block up to date"
  else
    backup "$ZSHRC"
    (( DRY )) || BLOCK="$BLOCK" "$PY" - "$ZSHRC" "$BEGIN" "$END" <<'PY'
import os, re, sys
p, b, e = sys.argv[1:4]
s = open(p).read()
s = re.sub(re.escape(b) + r".*?" + re.escape(e), lambda m: os.environ["BLOCK"], s, flags=re.S)
open(p, "w").write(s)
PY
    say "updated block"
  fi
else
  backup "$ZSHRC"
  (( DRY )) || print -r -- $'\n'"$BLOCK" >> "$ZSHRC"
  say "added block"
fi
# Things a manual setup may have left behind that now duplicate the package
local legacy
legacy=$(grep -nE "claude-new\.zsh|alias claude-(${(j:|:)PROFILES})=|^(y|ws)\(\) *\{" "$ZSHRC" 2>/dev/null | grep -v worksessions || true)
if [[ -n "$legacy" ]]; then
  warn "~/.zshrc still has older definitions the package now provides — remove them:"
  print -r -- "$legacy" | sed 's/^/      /'
fi

step "Done"
say "Open a new terminal (or: source ~/.zshrc), then try:  claude-new -l   ·   ws   ·   claude-audit"
(( DRY )) && say "(dry run — nothing was changed)"
exit 0
