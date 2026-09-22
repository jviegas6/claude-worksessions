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
# Seed vocabulary for a session's task type; what you actually use is learned from
# past sessions and suggested first.
: ${CWS_TASK_TYPES:="permissions, job errors, new features, security, investigation, data quality, tooling, documentation"}

# Default profile for a bare `claude`
export CLAUDE_CONFIG_DIR="$HOME/.claude-$CWS_DEFAULT_PROFILE"

# `-p NAME` for claude-new and claude-resume: NAME must be one of CWS_PROFILES.
_cws_check_profile() {
  local cmd="$1" name="$2"
  local -a profiles=(${=CWS_PROFILES})
  if [[ -z "$name" || "$name" == -* ]]; then
    print -u2 -- "$cmd: -p needs a profile name (one of: ${profiles[*]})"
    return 1
  fi
  if (( ! ${profiles[(Ie)$name]} )); then
    print -u2 -- "$cmd: unknown profile '$name' (one of: ${profiles[*]}; see claude-new -L)"
    return 1
  fi
}

# Claude Code with a profile: `claude-resume -p work --resume ID`. Everything but -p goes
# to claude unchanged; with nothing else it adds --resume, which opens the session picker.
# `--` ends claude-resume's options, for claude's own -p (print mode).
claude-resume() {
  emulate -L zsh
  local profile="$CWS_DEFAULT_PROFILE"
  case "$1" in
    -p|--profile) _cws_check_profile claude-resume "$2" || return 1; profile="$2"; shift 2 ;;
    -h|--help)
      print -r -- 'claude-resume [-p PROFILE] [--] [claude args...]'
      print -r -- "    run Claude Code with a profile (${=CWS_PROFILES}; default $CWS_DEFAULT_PROFILE)"
      print -r -- '    no claude args: --resume, i.e. pick a session to resume'
      return 0 ;;
  esac
  [[ "$1" == -- ]] && shift
  (( $# )) || set -- --resume
  local cfg="$HOME/.claude-$profile"
  if [[ ! -d "$cfg" ]]; then
    print -u2 -- "claude-resume: config dir $cfg does not exist"
    return 1
  fi
  CLAUDE_CONFIG_DIR="$cfg" command claude "$@"
}

# --- task type ---------------------------------------------------------------------
# What kind of work a session is: permissions, job errors, new features, security, ...
# The list is learned from past sessions (most recent first), then the seeds above.
_cws_task_types() {
  "$CWS_PYTHON" - "$CLAUDE_WORK_ROOT" "$CWS_TASK_TYPES" <<'PYEOF'
import glob, json, os, sys
root, seeds = sys.argv[1], sys.argv[2]
seen, out = set(), []
files = glob.glob(os.path.join(root, "[0-9]" * 4, "[0-9][0-9]", "[0-9][0-9]", "*", ".session.json"))
for f in sorted(files, reverse=True):                    # newest folder first
    try:
        t = (json.load(open(f)).get("task_type") or "").strip()
    except (ValueError, OSError):
        continue
    if t and t.lower() not in seen:
        seen.add(t.lower()); out.append(t)
for t in (x.strip() for x in seeds.split(",")):
    if t and t.lower() not in seen:
        seen.add(t.lower()); out.append(t)
print("\n".join(out))
PYEOF
}

# A first guess from the session name; the user can always type their own.
_cws_guess_type() {
  local n="${1:l}"
  case "$n" in
    *permission*|*access*|*rbac*|*grant*|*entitlement*) print -r -- "permissions" ;;
    *error*|*fail*|*debug*|*broken*|*timeout*|*incident*|*outage*) print -r -- "job errors" ;;
    *secret*|*security*|*vulnerab*|*gdpr*|*masking*) print -r -- "security" ;;
    *duplicat*|*quality*|*reconcil*|*mismatch*) print -r -- "data quality" ;;
    *migrat*|*build*|*implement*|*design*|*setup*|*new*) print -r -- "new features" ;;
    *doc*|*guide*|*runbook*) print -r -- "documentation" ;;
    *investigat*|*analys*|*analyz*|*check*|*audit*|*why*) print -r -- "investigation" ;;
    *) print -r -- "" ;;
  esac
}

# The id of the session running in a folder: Claude names its transcript <id>.jsonl in
# ~/.claude-<profile>/projects/<folder path with non-alphanumerics as dashes>/.
_cws_session_id() {
  "$CWS_PYTHON" - "$1" "$HOME" "$CWS_PROFILES" <<'PYEOF'
import glob, os, re, sys
folder, home, profiles = sys.argv[1], sys.argv[2], sys.argv[3].split()
enc = re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(folder))
best, when = "", -1.0
for p in profiles:
    for f in glob.glob(os.path.join(home, ".claude-" + p, "projects", enc, "*.jsonl")):
        m = os.path.getmtime(f)
        if m > when:
            best, when = os.path.basename(f)[:-6], m
print(best)
PYEOF
}

# claude-type [TYPE]            show or change the current session's task type
# claude-type --backfill [--apply]   guess a type for older sessions that have none
claude-type() {
  emulate -L zsh
  if [[ "$1" == --backfill ]]; then
    local apply=0 f name guess n=0
    [[ "$2" == --apply ]] && apply=1
    for f in "$CLAUDE_WORK_ROOT"/[0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9]/*/.session.json(N); do
      "$CWS_PYTHON" -c 'import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if (d.get("task_type") or "").strip() else 1)' "$f" && continue
      name=$("$CWS_PYTHON" -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("name") or d.get("slug") or "")' "$f")
      guess="$(_cws_guess_type "$name")"
      [[ -z "$guess" ]] && guess="investigation"
      printf '  %-18s %s\n' "$guess" "${${f:h}#$CLAUDE_WORK_ROOT/}"
      (( n++ ))
      if (( apply )); then
        WS_TYPE="$guess" "$CWS_PYTHON" -c '
import json, os, sys
p = sys.argv[1]
d = json.load(open(p))
d["task_type"] = os.environ["WS_TYPE"]
json.dump(d, open(p, "w"), indent=2)' "$f"
      fi
    done
    if (( apply )); then print -r -- "  set $n session(s)"
    else print -r -- "  $n session(s) would be set -- run: claude-type --backfill --apply"; fi
    return 0
  fi
  local dir="$PWD" meta=""
  while [[ "$dir" == "$CLAUDE_WORK_ROOT"/* || "$dir" == "$CLAUDE_WORK_ROOT" ]]; do
    if [[ -f "$dir/.session.json" ]]; then meta="$dir/.session.json"; break; fi
    dir="${dir:h}"
  done
  if [[ -z "$meta" ]]; then
    print -u2 -- "claude-type: no .session.json here (not inside a session folder)"; return 1
  fi
  # --folder changes the request folder's default instead of this session
  local scope="session"
  if [[ "$1" == --folder ]]; then scope="folder"; shift; fi
  local sid=""
  [[ "$scope" == session ]] && sid="$(_cws_session_id "${meta:h}")"

  WS_SID="$sid" WS_SCOPE="$scope" WS_TYPE="${(j: :)@}" WS_SET="$#" "$CWS_PYTHON" - "$meta" <<'PYEOF'
import json, os, sys
p = sys.argv[1]
d = json.load(open(p))
sid, scope = os.environ["WS_SID"], os.environ["WS_SCOPE"]
per = d.setdefault("session_types", {}) if isinstance(d.get("session_types", {}), dict) else {}
folder_type = (d.get("task_type") or "").strip()
current = (per.get(sid) or "").strip() or folder_type

if os.environ["WS_SET"] == "0":                      # just show it
    where = "this session" if (sid and per.get(sid)) else "the request folder"
    print("{} ({})".format(current or "(none)", where))
    raise SystemExit(0)

new = os.environ["WS_TYPE"].strip()
if scope == "folder" or not sid:
    d["task_type"] = new
    where = "request folder"
    if not sid and scope == "session":
        print("claude-type: no session transcript found here - setting the folder default",
              file=sys.stderr)
else:
    per[sid] = new
    d["session_types"] = per
    where = "session " + sid[:8]
json.dump(d, open(p, "w"), indent=2)
print("task type ({}): {} -> {}".format(where, current or "(none)", new))
PYEOF
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

  local profile="" name="" ticket="" canon="" dir slug cfg started ended audit=1 ttype=""
  local -a profiles=(${=CWS_PROFILES})

  while [[ "$1" == -* ]]; do
    case "$1" in
      -p|--profile)  _cws_check_profile claude-new "$2" || return 1; profile="$2"; shift 2 ;;
      -L|--profiles)
        local p desc url tag
        for p in $profiles; do
          desc="CWS_PROFILE_${p}_DESC" url="CWS_PROFILE_${p}_BASE_URL" tag=""
          [[ "$p" == "$CWS_DEFAULT_PROFILE" ]] && tag+=" default"
          [[ "$p" == "${CWS_SHARED_PROFILE:-${profiles[1]}}" ]] && tag+=" shared"
          [[ -d "$HOME/.claude-$p" ]] || tag+=" (no ~/.claude-$p)"
          printf '  %-12s %-18s %s\n' "$p" "${tag# }" \
            "${(P)desc:-}${${(P)url}:+  [${(P)url}]}"
        done
        return 0 ;;
      -n|--no-audit) audit=0;          shift ;;
      -T|--type)     ttype="$2";       shift 2 ;;
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
print("{:<10} {:<14} {:<16} {:<9}".format("[" + (d.get("profile") or "?") + "]", d.get("ticket") or "-",
                                  (d.get("task_type") or "-")[:16],
                                  "no-audit" if d.get("audit") is False else ""))' "$meta" 2>/dev/null)
          printf '  %s %s\n' "$info" "${d#$CLAUDE_WORK_ROOT/}"
        done
        return 0 ;;
      -h|--help)
        print -r -- 'claude-new [-p PROFILE] [-n] [-t TICKET] [-T TYPE] [name]'
        print -r -- '    create a YYYY/MM/DD/HH-mm-ss_slug folder and start Claude in it'
        print -r -- "    TICKET is mandatory: PREFIX-123 (e.g. $CWS_TICKET_EXAMPLE), or Other"
        print -r -- '    -T / --type is the kind of work (permissions, job errors, ...); asked if omitted'
        print -r -- '    -n / --no-audit keeps the session out of claude-audit and the weekly review'
        print -r -- '    (claude-search still finds it)'
        print -r -- "    -p / --profile picks the profile (${profiles[*]}); asked if omitted"
        print -r -- 'claude-new -l    list recent sessions'
        print -r -- 'claude-new -L    list the configured profiles'
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

  # Task type: what kind of work this is. Suggested from the name, chosen from what
  # you have used before, or typed fresh.
  if [[ -z "$ttype" ]]; then
    local -a types=("${(@f)$(_cws_task_types)}")
    local guess="$(_cws_guess_type "$name")" pick="" i=1 t tries=0
    if [[ -t 0 ]]; then
      print -r -- ""
      # The type is what STARTED the work, not everything it touches on the way:
      # a job error that needs investigation, a permission change and a doc update
      # is still "job errors".
      if [[ -n "$guess" ]]; then
        print -r -- "  Task type — what kind of work starts this? (Enter for '$guess', a number, your own words, - for none)"
      else
        print -r -- "  Task type — what kind of work starts this? Nothing in the name matched, so pick one:"
      fi
      for t in $types; do printf '    %d) %s\n' $i "$t"; (( i++ )); done
      while true; do
        read "pick?Task type${guess:+ [$guess]}: " || return 1
        if [[ -z "$pick" && -z "$guess" ]]; then
          (( tries++ ))
          (( tries >= 2 )) && { ttype=""; break; }
          print -u2 -- "  pick a number, type your own, or - for none"
          continue
        fi
        case "$pick" in
          "")  ttype="$guess" ;;
          -)   ttype="" ;;
          <->) if (( pick >= 1 && pick <= ${#types} )); then ttype="${types[$pick]}"; else ttype="$pick"; fi ;;
          *)   ttype="$pick" ;;
        esac
        break
      done
    else
      ttype="$guess"
    fi
  fi
  [[ "$ttype" == "-" ]] && ttype=""

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
  WS_NAME="$name" WS_PROFILE="$profile" WS_TICKET="$ticket" WS_SLUG="$slug" WS_TYPE="$ttype" \
  WS_STARTED="$started" WS_DIR="$dir" WS_AUDIT="$audit" \
    "$CWS_PYTHON" -c '
import json, os, socket
p = os.path.join(os.environ["WS_DIR"], ".session.json")
json.dump({
    "name":       os.environ["WS_NAME"],
    "slug":       os.environ["WS_SLUG"],
    "profile":    os.environ["WS_PROFILE"],
    "ticket":     os.environ["WS_TICKET"],
    "task_type":  os.environ.get("WS_TYPE", ""),
    "audit":      os.environ["WS_AUDIT"] == "1",
    "started_at": os.environ["WS_STARTED"],
    "ended_at":   None,
    "host":       socket.gethostname(),
    "path":       os.environ["WS_DIR"],
}, open(p, "w"), indent=2)
'

  print -r -- "→ $profile  $ticket  ${ttype:+[$ttype]  }${dir#$CLAUDE_WORK_ROOT/}${${audit:#1}:+  (no-audit)}"
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
