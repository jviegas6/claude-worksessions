# claude-worksessions: shell side. Sourced from ~/.zshrc by install.sh.
#
#   claude-<profile>      Claude Code with that profile's config dir (~/.claude-<profile>)
#   claude-new            create a YYYY/MM/DD/HH-mm-ss_slug request folder and start Claude in it
#   ws [-o|-c|-y]         fuzzy-pick a request folder and cd into it (Finder / VS Code / yazi)
#   y                     yazi, and cd to wherever you quit it

# --- configuration ---------------------------------------------------------------
_cws_load_config() {
  local f="${CWS_CONFIG:-$HOME/.config/claude-worksessions/config.env}"
  [[ -r "$f" ]] || { print -u2 -- "claude-worksessions: no config at $f (run install.sh)"; return 1; }
  # KEY="value" lines only; anything else in the file is ignored
  setopt local_options no_extended_glob
  local line key val
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ '^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)=(.*)$' ]] || continue
    key="${match[1]}"; val="${match[2]}"
    if [[ "$val" == \"* ]]; then          # "quoted" -- up to the closing quote
      val="${val#\"}"; val="${val%%\"*}"
    elif [[ "$val" == \'* ]]; then
      val="${val#\'}"; val="${val%%\'*}"
    else                                   # bare -- drop " # comment" and trailing blanks
      val="${val%%[[:space:]]#*}"
      while [[ "$val" == *[[:space:]] ]]; do val="${val%?}"; done
    fi
    val="${val//\$\{HOME\}/$HOME}"; val="${val//\$HOME/$HOME}"
    typeset -g "$key=$val"
  done < "$f"
}
_cws_load_config

# Python for the small JSON helpers: the system one if it is there, else any python3
if [[ -z "${CWS_PYTHON:-}" || ! -x "${CWS_PYTHON:-}" ]]; then
  if [[ -x /usr/bin/python3 ]]; then export CWS_PYTHON=/usr/bin/python3
  else export CWS_PYTHON="$(command -v python3 2>/dev/null)"; fi
fi

export CWS_CONFIG="${CWS_CONFIG:-$HOME/.config/claude-worksessions/config.env}"
export CLAUDE_WORK_ROOT="${CWS_WORK_ROOT:-${CLAUDE_WORK_ROOT:-$HOME/work_sessions}}"
: ${CWS_PROFILES:="personal work"}
: ${CWS_DEFAULT_PROFILE:=${${=CWS_PROFILES}[1]}}
: ${CWS_TICKET_EXAMPLE:="PROJ-123"}

# Default profile for a bare `claude`
export CLAUDE_CONFIG_DIR="$HOME/.claude-$CWS_DEFAULT_PROFILE"

# One alias per profile: claude-personal, claude-work, ...
() {
  local p
  for p in ${=CWS_PROFILES}; do
    alias "claude-$p=CLAUDE_CONFIG_DIR=\$HOME/.claude-$p claude"
  done
}

# --- claude-new --------------------------------------------------------------------
_claude_new_ticket() {
  # Normalise a ticket to PREFIX-123 or Other; non-zero if it is neither.
  local t="${1:u}"
  t="${t//[[:space:]]/}"
  case "$t" in
    OTHER|NONE|-) print -r -- "Other"; return 0 ;;
  esac
  [[ "$t" =~ '^[A-Z][A-Z0-9]+-[0-9]+$' ]] || return 1
  print -r -- "$t"
}

claude-new() {
  emulate -L zsh
  setopt local_options no_nomatch

  local profile="" name="" ticket="" canon="" dir slug cfg started ended audit=1
  local -a profiles=(${=CWS_PROFILES})

  while [[ "$1" == -* ]]; do
    case "$1" in
      -w|--work)     profile=work;     shift ;;
      -p|--personal) profile=personal; shift ;;
      -P|--profile)  profile="$2";     shift 2 ;;
      -n|--no-audit) audit=0;          shift ;;
      -t|--ticket)
        if [[ -z "$2" ]]; then
          print -u2 -- "claude-new: -t needs a ticket (e.g. $CWS_TICKET_EXAMPLE, or Other)"
          return 1
        fi
        ticket="$2"; shift 2 ;;
      -l|--list)
        print -r -- "Recent sessions in $CLAUDE_WORK_ROOT:"
        local d
        for d in "$CLAUDE_WORK_ROOT"/[0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9]/*(/On[1,15]N); do
          local meta="$d/.session.json" info="?"
          [[ -f $meta ]] && info=$("$CWS_PYTHON" -c 'import json,sys
d = json.load(open(sys.argv[1]))
print("{:<10} {:<14} {:<9}".format("[" + (d.get("profile") or "?") + "]", d.get("ticket") or "-",
                                  "no-audit" if d.get("audit") is False else ""))' "$meta" 2>/dev/null)
          printf '  %s %s\n' "$info" "${d#$CLAUDE_WORK_ROOT/}"
        done
        return 0 ;;
      -h|--help)
        print -r -- 'claude-new [-w|-p|-P PROFILE] [-n] [-t TICKET] [name]'
        print -r -- '    create a YYYY/MM/DD/HH-mm-ss_slug folder and start Claude in it'
        print -r -- "    TICKET is mandatory: PREFIX-123 (e.g. $CWS_TICKET_EXAMPLE), or Other"
        print -r -- '    -n / --no-audit keeps the session out of claude-audit and the weekly review'
        print -r -- '    (claude-search still finds it)'
        print -r -- "    profiles: ${profiles[*]}  (-w = work, -p = personal)"
        print -r -- 'claude-new -l    list recent sessions'
        return 0 ;;
      *) print -u2 -- "claude-new: unknown option $1"; return 1 ;;
    esac
  done

  # A ticket-shaped first word is the ticket: `claude-new PROJ-123 azure cost`.
  if [[ -z "$ticket" && "${1:u}" =~ '^[A-Z][A-Z0-9]+-[0-9]+$' ]]; then
    ticket="$1"; shift
  fi

  name="$*"
  if [[ -z "$name" ]]; then
    read "name?Session name: " || return 1
  fi
  if [[ -z "${name//[[:space:]]/}" ]]; then
    print -u2 -- "claude-new: a session name is required"
    return 1
  fi

  while true; do
    if [[ -z "$ticket" ]]; then
      read "ticket?Jira ticket (e.g. $CWS_TICKET_EXAMPLE, or Other): " || return 1
      if [[ -z "${ticket//[[:space:]]/}" ]]; then
        print -u2 -- "claude-new: a ticket is required -- use Other if there is none"
        return 1
      fi
    fi
    if canon=$(_claude_new_ticket "$ticket"); then
      ticket="$canon"
      break
    fi
    print -u2 -- "claude-new: '$ticket' is not a ticket -- expected PREFIX-123 (e.g. $CWS_TICKET_EXAMPLE) or Other"
    ticket=""
    [[ -t 0 ]] || return 1  # not interactive: fail rather than loop
  done

  if [[ -z "$profile" ]]; then
    if (( ${#profiles} == 1 )); then
      profile="${profiles[1]}"
    else
      print -r -- ""
      local i=1 p desc def=1
      for p in $profiles; do
        desc="CWS_PROFILE_${p}_DESC"
        printf '  %d) %-10s - %s\n' $i "$p" "${(P)desc:-}"
        [[ "$p" == "$CWS_DEFAULT_PROFILE" ]] && def=$i
        (( i++ ))
      done
      local choice=""
      read "choice?Profile [$def]: " || return 1
      choice="${choice:-$def}"
      if [[ "$choice" == <-> ]] && (( choice >= 1 && choice <= ${#profiles} )); then
        profile="${profiles[$choice]}"
      elif (( ${profiles[(Ie)$choice]} )); then
        profile="$choice"
      else
        print -u2 -- "claude-new: invalid profile choice '$choice'"; return 1
      fi
    fi
  fi

  cfg="$HOME/.claude-$profile"
  if [[ ! -d "$cfg" ]]; then
    print -u2 -- "claude-new: config dir $cfg does not exist"
    return 1
  fi

  # slugify: lowercase, non-alphanumerics to dashes, collapse, trim, cap at 60 chars
  slug="${name:l}"
  slug="${slug//[^a-z0-9]/-}"
  while [[ "$slug" == *--* ]]; do slug="${slug//--/-}"; done
  slug="${slug#-}"; slug="${slug%-}"
  slug="${slug[1,60]}"; slug="${slug%-}"
  [[ -z "$slug" ]] && slug="session"

  # YYYY/MM/DD/HH-mm-ss_slug (no colons: OneDrive rejects them)
  dir="$CLAUDE_WORK_ROOT/$(date +%Y/%m/%d/%H-%M-%S)_$slug"
  if [[ -e "$dir" ]]; then
    local n=2
    while [[ -e "${dir}-${n}" ]]; do (( n++ )); done
    dir="${dir}-${n}"
  fi

  if ! mkdir -p "$dir"; then
    print -u2 -- "claude-new: could not create $dir"
    return 1
  fi

  started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  WS_NAME="$name" WS_PROFILE="$profile" WS_TICKET="$ticket" WS_SLUG="$slug" \
  WS_STARTED="$started" WS_DIR="$dir" WS_AUDIT="$audit" \
    "$CWS_PYTHON" -c '
import json, os, socket
p = os.path.join(os.environ["WS_DIR"], ".session.json")
json.dump({
    "name":       os.environ["WS_NAME"],
    "slug":       os.environ["WS_SLUG"],
    "profile":    os.environ["WS_PROFILE"],
    "ticket":     os.environ["WS_TICKET"],
    "audit":      os.environ["WS_AUDIT"] == "1",
    "started_at": os.environ["WS_STARTED"],
    "ended_at":   None,
    "host":       socket.gethostname(),
    "path":       os.environ["WS_DIR"],
}, open(p, "w"), indent=2)
'

  print -r -- "→ $profile  $ticket  ${dir#$CLAUDE_WORK_ROOT/}${${audit:#1}:+  (no-audit)}"
  cd "$dir" || return 1

  CLAUDE_CONFIG_DIR="$cfg" command claude
  local rc=$?

  ended="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  WS_ENDED="$ended" WS_DIR="$dir" "$CWS_PYTHON" -c '
import json, os
p = os.path.join(os.environ["WS_DIR"], ".session.json")
try:
    d = json.load(open(p))
except Exception:
    raise SystemExit(0)
d["ended_at"] = os.environ["WS_ENDED"]
json.dump(d, open(p, "w"), indent=2)
' 2>/dev/null

  return $rc
}

# --- navigation ----------------------------------------------------------------------
# y: browse with yazi; quitting leaves the shell in the folder you were in
y() {
  local tmp="$(mktemp -t yazi-cwd.XXXXXX)" cwd
  yazi "$@" --cwd-file="$tmp"
  IFS= read -r -d '' cwd < "$tmp"
  [[ -n "$cwd" && "$cwd" != "$PWD" ]] && builtin cd -- "$cwd"
  rm -f -- "$tmp"
}

# ws: fuzzy-pick a request folder (newest first) and cd into it
#   ws -o  also open in Finder · ws -c  also open in VS Code · ws -y  also browse with yazi
ws() {
  local root="$CLAUDE_WORK_ROOT" d
  d=$(cd "$root" && print -rl -- [0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9]/*(/On) | fzf --height=60% --reverse \
        --preview "ls -la $root/{}") || return
  cd "$root/$d" || return
  case $1 in
    -o) open . ;;
    -c) code . ;;
    -y) y ;;
  esac
}
