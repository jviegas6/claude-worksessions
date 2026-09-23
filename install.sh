#!/usr/bin/env zsh
# claude-worksessions installer for macOS, Linux and Windows (WSL). Safe to re-run: every
# step checks before it acts, and anything it replaces is backed up first.
#
#   ./install.sh                      install / update using your config
#   ./install.sh --config FILE        use this config.env
#   ./install.sh --dry-run            print what would change, change nothing
#   ./install.sh --no-brew            don't install packages (Homebrew, apt, dnf, ...)
#   ./install.sh --no-bootstrap       don't install anything missing, just report it
#   ./install.sh --profiles           add/remove/rename profiles, then install
#   ./install.sh --update [vX.Y.Z]    move the checkout to the newest (or named) release
#   ./install.sh --edge               move the checkout to main, then install
#   ./install.sh --yes                don't prompt (tokens are then skipped)

[ -n "$ZSH_VERSION" ] || { echo "install.sh needs zsh: install it (e.g. sudo apt install zsh), then run: zsh ./install.sh" >&2; exit 1; }
emulate -L zsh
setopt pipe_fail

REPO="${0:A:h}"
VERSION="$(<"$REPO/VERSION")"
DRY=0 BREW=1 YES=0 NOBOOT=0 RECONF=0 UPDATE=0 EDGE=0 TARGET="" CONFIG=""
STAMP="$(date +%Y%m%d-%H%M%S)"

while (( $# )); do
  case "$1" in
    --config)  CONFIG="${2:A}"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    --no-brew) BREW=0; shift ;;
    --no-bootstrap) NOBOOT=1; BREW=0; shift ;;
    --profiles|--reconfigure) RECONF=1; shift ;;
    --update)  UPDATE=1; shift
               if [[ "$1" == v* ]]; then TARGET="$1"; shift; fi ;;
    --edge)    UPDATE=1; EDGE=1; shift ;;
    --yes|-y)  YES=1; shift ;;
    -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) print -u2 "install.sh: unknown option $1"; exit 1 ;;
  esac
done

say()  { print -r -- "  $*"; }
step() { print -r -- ""; print -r -- "▸ $*"; }
warn() { print -u2 -r -- "  ! $*"; }
run()  { if (( DRY )); then print -r -- "    [dry-run] $*"; else "$@"; fi; }

# Python for the JSON/config helpers. Re-resolved after the prerequisites step,
# which can install one if this machine has none.
resolve_py() {
  if [[ -x /usr/bin/python3 ]]; then PY=/usr/bin/python3
  elif command -v python3 >/dev/null 2>&1; then PY="$(command -v python3)"
  else PY=""; fi
}
resolve_py

# mac, linux or wsl (Windows Subsystem for Linux). CWS_OS overrides, for tests.
detect_os() {
  if [[ -n "$CWS_OS" ]]; then print -r -- "$CWS_OS"; return; fi
  case "$(uname -s)" in
    Darwin) print -r -- mac ;;
    Linux)  grep -qsi microsoft /proc/version && print -r -- wsl || print -r -- linux ;;
    *)      print -r -- linux ;;
  esac
}
OS="$(detect_os)"

# Where the work root goes by default: on WSL the Windows OneDrive folder if there is one
# (work first, then personal), so it syncs like it does on a Mac.
default_work_root() {
  if [[ "$OS" == wsl ]] && command -v cmd.exe >/dev/null 2>&1 && command -v wslpath >/dev/null 2>&1; then
    local var od
    for var in OneDriveCommercial OneDrive; do
      od="$(cd /mnt/c 2>/dev/null; cmd.exe /d /c "echo %$var%" 2>/dev/null | tr -d '\r')"
      if [[ -n "$od" && "$od" != *%* ]]; then print -r -- "$(wslpath -u "$od")/work_sessions"; return; fi
    done
  fi
  print -r -- "$HOME/work_sessions"
}

# Local IANA zone, and the name Outlook uses for it (a guess the user can correct)
local_timezone() {
  local tz="$(readlink /etc/localtime 2>/dev/null)"
  tz="${tz#*/zoneinfo/}"
  print -r -- "${tz:-UTC}"
}
windows_timezone() {
  case "$1" in
    Europe/London|Europe/Lisbon|Europe/Dublin) print -r -- "GMT Standard Time" ;;
    Europe/Paris|Europe/Brussels|Europe/Madrid) print -r -- "Romance Standard Time" ;;
    Europe/Berlin|Europe/Amsterdam|Europe/Rome|Europe/Vienna|Europe/Stockholm|Europe/Zurich) print -r -- "W. Europe Standard Time" ;;
    Europe/Lisbon) print -r -- "GMT Standard Time" ;;
    America/New_York|America/Toronto) print -r -- "Eastern Standard Time" ;;
    America/Chicago) print -r -- "Central Standard Time" ;;
    America/Denver) print -r -- "Mountain Standard Time" ;;
    America/Los_Angeles|America/Vancouver) print -r -- "Pacific Standard Time" ;;
    Asia/Kolkata|Asia/Calcutta) print -r -- "India Standard Time" ;;
    Australia/Sydney|Australia/Melbourne) print -r -- "AUS Eastern Standard Time" ;;
    UTC|Etc/UTC) print -r -- "UTC" ;;
    *) print -r -- "" ;;
  esac
}
# On WSL, Windows knows its own zone name better than the table above.
[[ "$OS" == wsl ]] && command -v powershell.exe >/dev/null 2>&1 && windows_timezone() {
  local id="$(cd /mnt/c 2>/dev/null; powershell.exe -NoProfile -Command '(Get-TimeZone).Id' 2>/dev/null | tr -d '\r')"
  print -r -- "$id"
}

# --- updating the checkout ---------------------------------------------------------
newest_tag() { git -C "$REPO" tag -l 'v*' 2>/dev/null | sort -V | tail -1 }

# Move the checkout to a newer release (or to main with --edge). Config, work folders,
# profiles and history are never touched — only the checkout and what is rendered from it.
update_repo() {
  local target="$1" from="$VERSION" to=""
  command -v git >/dev/null 2>&1 || { warn "git is not installed — update by hand"; return 1; }
  git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1 || { warn "$REPO is not a git checkout — update by hand"; return 1; }
  say "fetching…"
  git -C "$REPO" fetch --tags --quiet 2>/dev/null || warn "fetch failed — using the tags already here"
  if [[ -n "$(git -C "$REPO" status --porcelain)" ]]; then
    warn "the checkout has local changes — commit or stash them first:"
    git -C "$REPO" status --short | sed 's/^/      /'
    return 1
  fi
  if [[ -n "$target" ]]; then to="$target"
  elif (( EDGE )); then to="main"
  else to="$(newest_tag)"; fi
  [[ -n "$to" ]] || { warn "no releases found"; return 1; }
  if [[ "$to" == "main" ]]; then
    git -C "$REPO" checkout -q main && git -C "$REPO" pull -q --ff-only || { warn "could not move to main"; return 1; }
  else
    git -C "$REPO" checkout -q "$to" || { warn "could not check out $to"; return 1; }
  fi
  VERSION="$(<"$REPO/VERSION")"
  if [[ "$from" == "$VERSION" ]]; then
    say "already on $VERSION — re-installing it"
  elif [[ "$(print -rl -- "$from" "$VERSION" | sort -V | tail -1)" == "$from" ]]; then
    say "rolled back $from → $VERSION"
  else
    say "$from → $VERSION"
    [[ -n "$PY" ]] && "$PY" - "$REPO/CHANGELOG.md" "$from" <<'PY'
import re, sys
path, frm = sys.argv[1], sys.argv[2]
out, seen = [], False
for block in re.split(r"(?m)^## ", open(path).read())[1:]:
    ver = block.split("]")[0].lstrip("[")
    if ver == frm:
        break
    out.append("## " + block.rstrip())
print("\n".join("    " + l for l in "\n\n".join(out).splitlines()) if out else "")
PY
  fi
  return 0
}

# One line when a newer release exists; fetches at most once a day
version_notice() {
  git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1 || return 0
  local head="$REPO/.git/FETCH_HEAD"
  if [[ ! -f "$head" || -n "$(find "$head" -mtime +1 2>/dev/null)" ]]; then
    git -C "$REPO" fetch --tags --quiet 2>/dev/null || return 0
  fi
  local newest="$(newest_tag)"
  [[ -n "$newest" && "$newest" != "v$VERSION" ]] && \
    say "v$VERSION installed · $newest available — ./install.sh --update"
  return 0
}

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
  [[ -f "$src" ]] || { warn "template missing: $src — skipped $dst"; return 1; }
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
  # A failed render must never overwrite what is already there
  if (( $? != 0 )) || [[ ! -s "$tmp" ]]; then
    rm -f "$tmp"; warn "could not render $src — left $dst alone"; return 1
  fi
  if [[ -f "$dst" ]] && cmp -s "$tmp" "$dst"; then
    say "unchanged $dst"; rm -f "$tmp"; return 0
  fi
  [[ -f "$dst" ]] && backup "$dst"
  run mkdir -p "${dst:h}"
  if (( DRY )); then print -r -- "    [dry-run] write $dst"; rm -f "$tmp"; else mv "$tmp" "$dst"; say "wrote $dst"; fi
}

# Set KEY="value" in a config.env, replacing the line if it is there
cws_set() {
  local key="$1" val="$2" file="$3"
  if grep -q "^${key}=" "$file" 2>/dev/null; then
    "$PY" - "$file" "$key" "$val" <<'PY'
import re, sys
path, key, val = sys.argv[1:4]
s = open(path).read()
s = re.sub(r"(?m)^%s=.*$" % re.escape(key), '%s="%s"' % (key, val.replace('"', '\\"')), s)
open(path, "w").write(s)
PY
  else
    print -r -- "${key}=\"${val}\"" >> "$file"
  fi
}

# Ask about profiles and write them to config.env. Any number; each is either a
# Claude subscription login or an Anthropic-compatible inference gateway.
configure_profiles() {
  local file="$1"
  local -a names=() kinds=() descs=() urls=()
  local name kind desc url current="${CWS_PROFILES:-}"
  print -r -- ""
  print -r -- "  A profile is a separate Claude Code login with its own config dir"
  print -r -- "  (~/.claude-<name>), run with claude-resume -p <name>. They share history,"
  print -r -- "  projects and skills, so every session shows up in claude-audit."
  [[ -n "$current" ]] && print -r -- "  Current: $current"
  print -r -- ""
  while true; do
    if (( ${#names} )); then
      read "name?  Another profile name (Enter to finish): "
      [[ -z "$name" ]] && break
    else
      read "name?  First profile name [personal]: "
      name="${name:-personal}"
    fi
    # No dashes: the name goes into CWS_PROFILE_<name>_DESC / _BASE_URL, and a dash is not
    # valid in a variable name, so those settings would be silently ignored.
    if [[ ! "$name" =~ '^[a-z0-9][a-z0-9_]*$' ]]; then
      warn "use lowercase letters, digits and underscores (no dashes)"; continue
    fi
    if (( ${names[(Ie)$name]} )); then warn "'$name' already added"; continue; fi
    print -r -- "    1) Claude subscription (Pro/Max/Team) — sign in with your account"
    print -r -- "    2) Inference gateway / API — an Anthropic-compatible base URL and token"
    read "kind?    Type for '$name' [1]: "; kind="${kind:-1}"
    url=""
    if [[ "$kind" == 2 ]]; then
      while [[ -z "$url" ]]; do read "url?    Base URL (e.g. https://gateway.example.com): "; done
      desc_default="inference gateway"
    else
      desc_default="Claude subscription"
    fi
    read "desc?    One-line description [$desc_default]: "; desc="${desc:-$desc_default}"
    names+=("$name"); kinds+=("$kind"); descs+=("$desc"); urls+=("$url")
  done

  local def="${names[1]}" shared="${names[1]}"
  if (( ${#names} > 1 )); then
    read "def?  Default profile (a bare \`claude\`) [${names[1]}]: "; def="${def:-${names[1]}}"
    (( ${names[(Ie)$def]} )) || { warn "unknown profile '$def' — using ${names[1]}"; def="${names[1]}"; }
    print -r -- "  One profile owns the shared history, projects, skills, plugins and MCP;"
    print -r -- "  the others link to it. Pick the one you use most (usually the default)."
    read "shared?  Shared profile [$def]: "; shared="${shared:-$def}"
    (( ${names[(Ie)$shared]} )) || { warn "unknown profile '$shared' — using $def"; shared="$def"; }
  fi

  # Drop settings for profiles that are no longer listed, then write the new ones
  "$PY" - "$file" <<'PY'
import re, sys
path = sys.argv[1]
s = open(path).read()
s = re.sub(r"(?m)^CWS_PROFILE_[A-Za-z0-9_]+_(DESC|BASE_URL)=.*\n", "", s)
open(path, "w").write(s)
PY
  cws_set CWS_PROFILES "${names[*]}" "$file"
  cws_set CWS_DEFAULT_PROFILE "$def" "$file"
  cws_set CWS_SHARED_PROFILE "$shared" "$file"
  local i
  for i in {1..${#names}}; do
    cws_set "CWS_PROFILE_${names[$i]}_DESC" "${descs[$i]}" "$file"
    [[ -n "${urls[$i]}" ]] && cws_set "CWS_PROFILE_${names[$i]}_BASE_URL" "${urls[$i]}" "$file"
  done
  say "profiles written to $file: ${names[*]}"
  # Data is never deleted: say what is now unused rather than removing it
  local old
  for old in ${=current}; do
    (( ${names[(Ie)$old]} )) || say "'$old' is no longer listed — ~/.claude-$old is left as it is"
  done
}

# Ask for the rest of the settings. Defaults come from the current config.
configure_basics() {
  local file="$1" ans tz wtz
  local org="${CWS_ORG:-}" role="${CWS_USER_ROLE:-data/platform engineer}"
  read "ans?  Organisation (for the skills' wording) [${org:-none}]: "; org="${ans:-$org}"
  read "ans?  Your role [$role]: "; role="${ans:-$role}"
  tz="${CWS_TIMEZONE:-$(local_timezone)}"
  read "ans?  Time zone [$tz]: "; tz="${ans:-$tz}"
  wtz="${CWS_TIMEZONE_WINDOWS:-$(windows_timezone "$tz")}"
  read "ans?  Same zone as Outlook names it [${wtz:-UTC}]: "; wtz="${ans:-${wtz:-UTC}}"
  local ticket="${CWS_TICKET_EXAMPLE:-PROJ-123}"
  read "ans?  An example ticket key, for prompts [$ticket]: "; ticket="${ans:-$ticket}"
  local jira="${CWS_JIRA_CLOUD_ID:-}"
  read "ans?  Atlassian cloud id for the weekly review, if any [${jira:-none}]: "; jira="${ans:-$jira}"
  local yazi="${CWS_INSTALL_YAZI:-1}"
  read "ans?  Install the yazi/glow/pandoc Markdown extras? [Y/n]: "
  [[ "${${ans:-y}:l}" == y* ]] && yazi=1 || yazi=0
  cws_set CWS_ORG "$org" "$file"
  cws_set CWS_USER_ROLE "$role" "$file"
  cws_set CWS_TIMEZONE "$tz" "$file"
  cws_set CWS_TIMEZONE_WINDOWS "$wtz" "$file"
  cws_set CWS_TICKET_EXAMPLE "$ticket" "$file"
  cws_set CWS_JIRA_CLOUD_ID "$jira" "$file"
  cws_set CWS_INSTALL_YAZI "$yazi" "$file"
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

# Loop variables here are top-level, so they must not reuse a name a later `local` declares:
# zsh prints `name=value` when `local` re-declares a variable that is already set.
for req in shell/worksessions.zsh templates/CLAUDE.md.tmpl bin/claude-audit config/config.example.env; do
  [[ -f "$REPO/$req" ]] || { print -u2 "install.sh: $REPO is not a claude-worksessions checkout (no $req)"; exit 1; }
done

print -r -- "claude-worksessions $VERSION"

if (( UPDATE )); then
  step "Update"
  if (( DRY )); then say "[dry-run] would fetch and move the checkout"
  else update_repo "$TARGET" || exit 1; fi
fi

# --- 1. config -----------------------------------------------------------------------
step "Configuration"
LINK="$HOME/.config/claude-worksessions/config.env"
if [[ -z "$CONFIG" && -e "$LINK" ]]; then CONFIG="${LINK:A}"; fi
FIRST_RUN=0
if [[ -z "$CONFIG" ]]; then
  local root_default="$(default_work_root)" root
  if (( YES )); then root="$root_default"
  else read "root?  Work root (where request folders live) [$root_default]: "; root="${root:-$root_default}"; fi
  root="${~root}"
  CONFIG="$root/_config/config.env"
  if [[ ! -f "$CONFIG" ]]; then
    [[ -n "$PY" ]] || { print -u2 "install.sh: no python3 yet — run: xcode-select --install (Mac) or install python3 with your package manager"; exit 1; }
    run mkdir -p "${CONFIG:h}"
    if (( DRY )); then say "[dry-run] would create $CONFIG and ask about profiles"; exit 0; fi
    sed "s|^CWS_WORK_ROOT=.*|CWS_WORK_ROOT=\"${root/#$HOME/\$HOME}\"|" "$REPO/config/config.example.env" > "$CONFIG"
    say "created $CONFIG"
    FIRST_RUN=1
  fi
fi
[[ -f "$CONFIG" ]] || { print -u2 "install.sh: config $CONFIG not found"; exit 1; }
say "using $CONFIG"

# First run, or --profiles: ask instead of making them edit the file
if (( FIRST_RUN || RECONF )) && (( ! DRY && ! YES )); then
  # current values as defaults
  CWS_CONFIG="$CONFIG" source "$REPO/shell/worksessions.zsh" >/dev/null 2>&1
  unalias -m 'claude-*' 2>/dev/null || true
  # Answers overwrite the file, so keep the previous one
  (( FIRST_RUN )) || backup "$CONFIG"
  (( FIRST_RUN )) && configure_basics "$CONFIG"
  configure_profiles "$CONFIG"
fi
[[ "$CONFIG" == "${LINK:A}" ]] || link "$CONFIG" "$LINK"

# Load it exactly as the shell functions will
export CWS_CONFIG="$CONFIG"
source "$REPO/shell/worksessions.zsh" || { print -u2 "install.sh: could not load $REPO/shell/worksessions.zsh"; exit 1; }
unalias -m 'claude-*' 2>/dev/null || true
typeset -a PROFILES=(${=CWS_PROFILES})
for pname in $PROFILES; do
  [[ "$pname" =~ '^[a-z0-9][a-z0-9_]*$' ]] && continue
  print -u2 -r -- "install.sh: profile '$pname' in CWS_PROFILES is not valid -- use lowercase letters, digits and underscores (no dashes); run install.sh --profiles or edit $CONFIG"
  exit 1
done
: ${CWS_SHARED_PROFILE:=${PROFILES[1]}}
: ${CWS_ORG:=} ${CWS_USER_ROLE:=} ${CWS_TIMEZONE:=UTC} ${CWS_TIMEZONE_WINDOWS:=UTC} ${CWS_JIRA_CLOUD_ID:=} ${CWS_INSTALL_YAZI:=1}
export HOME CWS_WORK_ROOT="$CLAUDE_WORK_ROOT" CWS_ORG CWS_USER_ROLE CWS_TIMEZONE CWS_TIMEZONE_WINDOWS \
       CWS_TICKET_EXAMPLE CWS_JIRA_CLOUD_ID
say "work root  $CWS_WORK_ROOT"
say "profiles   ${PROFILES[*]} (default $CWS_DEFAULT_PROFILE, shared $CWS_SHARED_PROFILE)"

# --- 2. prerequisites --------------------------------------------------------------------
# Nothing here is assumed to be present. A clean Mac gets the Command Line Tools,
# Homebrew, Claude Code and the packages; Linux and WSL get them from the system package
# manager (apt, dnf, pacman or zypper), or from Homebrew when it is installed. All after
# one confirmation.
step "Prerequisites ($OS)"

brew_path() { [[ -x /opt/homebrew/bin/brew ]] && print -r -- /opt/homebrew/bin/brew ||
              { [[ -x /usr/local/bin/brew ]] && print -r -- /usr/local/bin/brew; } ||
              { [[ -x /home/linuxbrew/.linuxbrew/bin/brew ]] && print -r -- /home/linuxbrew/.linuxbrew/bin/brew; } }
have_clt()  { [[ "$OS" != mac ]] || /usr/bin/xcode-select -p >/dev/null 2>&1 }
have_brew() { command -v brew >/dev/null 2>&1 || [[ -n "$(brew_path)" ]] }
linux_pm()  { local pm; for pm in apt-get dnf pacman zypper; do command -v $pm >/dev/null 2>&1 && { print -r -- $pm; return; }; done }

# Where to get what the package manager may not have
typeset -A MANUAL=(
  yazi "https://yazi-rs.github.io/docs/installation"
  glow "https://github.com/charmbracelet/glow#installation"
)

# Install packages one at a time with the system package manager, so one it doesn't
# carry (yazi, glow on apt) doesn't stop the rest. Sets `failed`.
linux_install() {
  local pm="$1" pkg name; shift
  local -a sudo=()
  (( EUID )) && sudo=(sudo)
  [[ "$pm" == apt-get ]] && { $sudo apt-get update -qq >/dev/null || true }
  for pkg; do
    name="$pkg"
    [[ "$pkg" == python3 && "$pm" == pacman ]] && name=python
    case "$pm" in
      apt-get) $sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$name" >/dev/null 2>&1 ;;
      dnf)     $sudo dnf install -y -q "$name" >/dev/null 2>&1 ;;
      pacman)  $sudo pacman -S --noconfirm --needed "$name" >/dev/null 2>&1 ;;
      zypper)  $sudo zypper -n -q install "$name" >/dev/null 2>&1 ;;
    esac && say "installed $pkg" || failed+=("$pkg")
  done
}

typeset -a want=(fzf pandoc)   # pandoc: claude-md-email (Copy for email)
(( CWS_INSTALL_YAZI )) && want+=(yazi glow)
[[ "$OS" != mac ]] && want=(curl $want)
typeset -a pkgs_missing=() plan=() failed=()
local pkg
for pkg in $want; do command -v $pkg >/dev/null 2>&1 || pkgs_missing+=($pkg); done
PM=""
[[ "$OS" != mac ]] && PM="$(linux_pm)"
# Linux with Homebrew: use it, as on a Mac. Otherwise the system package manager.
USE_BREW=0
[[ "$OS" == mac ]] || have_brew && USE_BREW=1

have_clt  || plan+=("Xcode Command Line Tools (git, compilers — opens Apple's installer)")
[[ "$OS" == mac ]] && ! have_brew && plan+=("Homebrew (https://brew.sh — may ask for your admin password)")
command -v claude >/dev/null 2>&1 || plan+=("Claude Code (claude)")
if (( ${#pkgs_missing} )); then
  if (( USE_BREW )); then plan+=("Homebrew packages: ${pkgs_missing[*]}")
  elif [[ -n "$PM" ]]; then plan+=("$PM packages: ${pkgs_missing[*]} (may ask for your sudo password)")
  else plan+=("packages: ${pkgs_missing[*]} (no known package manager — install by hand)"); fi
fi

if (( ! ${#plan} )); then
  if [[ "$OS" == mac ]]; then say "all present: Command Line Tools, Homebrew, Claude Code, ${want[*]}"
  else say "all present: Claude Code, ${want[*]}"; fi
else
  print -r -- "  This machine is missing:"
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
    if [[ "$OS" == mac ]] && ! have_brew; then
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
    # curl first: the Claude Code installer needs it
    if (( ! USE_BREW && BREW )) && [[ -n "$PM" ]] && (( ${pkgs_missing[(Ie)curl]} )); then
      linux_install "$PM" curl
    fi
    if ! command -v claude >/dev/null 2>&1; then
      say "installing Claude Code…"
      curl -fsSL https://claude.ai/install.sh | bash || warn "Claude Code install failed — see https://docs.claude.com/claude-code"
      export PATH="$HOME/.local/bin:$PATH"
    fi
    pkgs_missing=(${pkgs_missing:#curl})
    if (( ${#pkgs_missing} )) && (( BREW )); then
      if (( USE_BREW )) && command -v brew >/dev/null 2>&1; then
        brew install $pkgs_missing || warn "brew install failed for: ${pkgs_missing[*]}"
      elif [[ -n "$PM" ]]; then
        linux_install "$PM" $pkgs_missing
      else
        failed+=($pkgs_missing)
      fi
      for pkg in $failed; do
        warn "could not install $pkg${MANUAL[$pkg]:+ — see ${MANUAL[$pkg]}}"
      done
    fi
  else
    warn "skipped — install by hand, then run ./install.sh again"
  fi
fi

# Python for the JSON helpers: the system one, else Homebrew's, else install it
resolve_py
if [[ -z "$PY" ]] && (( ! DRY )); then
  if (( USE_BREW )) && command -v brew >/dev/null 2>&1; then
    say "installing python…"; brew install python >/dev/null && resolve_py
  elif [[ -n "$PM" ]]; then
    linux_install "$PM" python3; resolve_py
  fi
fi
[[ -n "$PY" ]] || { print -u2 "install.sh: no python3 — install it (Command Line Tools, brew install python, or your package manager)"; exit 1; }
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
# The standing context is inlined, not imported: an @import in a parent CLAUDE.md is
# not expanded for sessions running in sub-folders, which is where every session runs.
CONTEXT="$(<"$CWS_WORK_ROOT/_config/context.md")" render "$REPO/templates/CLAUDE.md.tmpl" "$CWS_WORK_ROOT/CLAUDE.md"

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
  # Transcript retention: Claude Code deletes transcripts after cleanupPeriodDays (default
  # 30), and they are the audit trail. Set it long where it isn't set; a shorter value set
  # on purpose is left alone, with a warning.
  local keep=3650 kstate
  kstate=$(KEEP=$keep "$PY" - "$pdir/settings.json" <<'PY'
import json, os, sys
try:
    d = json.load(open(sys.argv[1]))
except FileNotFoundError:
    d = {}
except ValueError:
    print("unparsed"); raise SystemExit
keep, have = int(os.environ["KEEP"]), d.get("cleanupPeriodDays")
if isinstance(have, int) and not isinstance(have, bool):
    print("ok" if have >= keep else "short:%d" % have)
else:
    print("set")
PY
)
  case $kstate in
    ok)       say "$p: transcripts kept $keep+ days" ;;
    short:*)  warn "$p: cleanupPeriodDays is ${kstate#short:} — transcripts older than that are deleted, and the audit loses them" ;;
    unparsed) warn "$p: $pdir/settings.json isn't valid JSON — set \"cleanupPeriodDays\": $keep in it yourself" ;;
    set)      if (( DRY )); then say "[dry-run] $p: keep transcripts $keep days (cleanupPeriodDays)"
              else
                backup "$pdir/settings.json"
                KEEP=$keep "$PY" - "$pdir/settings.json" <<'PY'
import json, os, sys
p = sys.argv[1]
try:
    d = json.load(open(p))
except FileNotFoundError:
    d = {}
d["cleanupPeriodDays"] = int(os.environ["KEEP"])
perm = os.stat(p).st_mode & 0o777 if os.path.exists(p) else 0o644
open(p + ".tmp", "w").write(json.dumps(d, indent=2) + "\n")
os.chmod(p + ".tmp", perm)
os.replace(p + ".tmp", p)
PY
                say "$p: transcripts kept $keep days (was Claude Code's default, 30)"
              fi ;;
  esac
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
for b in claude-audit claude-search claude-sessions claude-vscode claude-md-email claude-delete; do link "$REPO/bin/$b" "$HOME/.local/bin/$b"; done

# --- 5a. VS Code ------------------------------------------------------------------------
# The Claude extension's env setting is machine-wide, so it can't follow a session's profile.
# Its process wrapper can: claude-vscode reads the profile from the folder's .session.json.
step "VS Code"
local vsdir vsset vsstate wrapper="$HOME/.local/bin/claude-vscode"
case $OS in
  mac) vsdir="$HOME/Library/Application Support/Code/User" ;;
  wsl) vsdir="$HOME/.vscode-server/data/Machine" ;;   # the extension runs inside WSL
  *)   vsdir="$HOME/.config/Code/User" ;;
esac
vsset="$vsdir/settings.json"
# vscode_wrapper check|write: prints "same", "set", "other:<old value>" or "unparsed"
vscode_wrapper() {
  WRAPPER="$wrapper" "$PY" - "$vsset" "$1" <<'PY'
import json, os, sys
p, mode = sys.argv[1:3]
key, want = "claudeCode.claudeProcessWrapper", os.environ["WRAPPER"]
try:
    d = json.load(open(p)) if os.path.getsize(p) else {}
except FileNotFoundError:
    d = {}
except ValueError:          # comments or trailing commas: VS Code allows them, json doesn't
    print("unparsed"); raise SystemExit
old = d.get(key)
print("same" if old == want else "other:" + old if old else "set")
if mode == "write" and old != want:
    d[key] = want
    open(p, "w").write(json.dumps(d, indent=4) + "\n")
PY
}
if [[ ! -d "$vsdir" ]]; then
  say "no VS Code settings in $vsdir — skipped"
else
  vsstate="$(vscode_wrapper check)"
  case $vsstate in
    same)     say "ok claudeCode.claudeProcessWrapper in $vsset" ;;
    unparsed) warn "$vsset isn't plain JSON — add this line to it yourself:"
              print -r -- "      \"claudeCode.claudeProcessWrapper\": \"$wrapper\"," ;;
    *)        if (( DRY )); then say "[dry-run] set claudeCode.claudeProcessWrapper in $vsset"
              else
                backup "$vsset"
                vscode_wrapper write >/dev/null
                say "set claudeCode.claudeProcessWrapper in $vsset"
                [[ $vsstate == other:* ]] && warn "it was ${vsstate#other:} before"
              fi ;;
  esac
fi

# The Work sessions sidebar: packaged here as a .vsix (no npm) and installed with `code`,
# at the repo's VERSION, so --update brings it along.
local ext_id="jviegas6.claude-worksessions" ext_want ext_have
ext_want="$(<"$REPO/VERSION")"
if ! command -v code >/dev/null 2>&1; then
  say "no 'code' command — skipped the Work sessions sidebar (VS Code: Shell Command: Install 'code' command in PATH)"
else
  ext_have="$(code --list-extensions --show-versions 2>/dev/null | grep -i "^$ext_id@" | cut -d@ -f2)"
  if [[ "$ext_have" == "$ext_want" ]]; then say "ok Work sessions sidebar $ext_want"
  elif (( DRY )); then say "[dry-run] install the Work sessions sidebar $ext_want${ext_have:+ (have $ext_have)}"
  else
    local vsix="$(mktemp -d)/claude-worksessions.vsix"
    if "$PY" "$REPO/vscode/package_vsix.py" "$vsix" >/dev/null &&
       code --install-extension "$vsix" --force >/dev/null 2>&1; then
      say "installed the Work sessions sidebar $ext_want — reload VS Code windows to load it"
    else
      warn "could not install the Work sessions sidebar — try: code --install-extension $vsix"
    fi
  fi
fi

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
(( UPDATE )) || version_notice
# Linux usually starts bash; the commands live in ~/.zshrc, so zsh must be the login shell
if [[ "${SHELL:t}" != zsh ]]; then
  warn "your login shell is ${SHELL:-unknown} — make it zsh so the commands load: chsh -s $(command -v zsh)"
fi
say "Open a new terminal (or: source ~/.zshrc), then try:  claude-new -l   ·   ws   ·   claude-audit"
(( DRY )) && say "(dry run — nothing was changed)"
exit 0
