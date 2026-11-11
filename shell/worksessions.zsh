# claude-worksessions: shell side. Sourced from ~/.zshrc by install.sh.
#
#   claude-new            create a YYYY/MM/DD/HH-mm-ss_slug request folder and open it (CWS_OPEN_CMD)
#   claude-goal           show or re-anchor the session goal claude-guard holds the session to
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
# The Claude config dirs whose transcripts are searched: CWS_CLAUDE_HOMES, else ~/.claude-<name>
# for each name in the older CWS_PROFILES, else ~/.claude. The app that runs Claude (T3, an IDE)
# picks which one a session uses; this list is only where to look.
if [[ -z "${CWS_CLAUDE_HOMES:-}" ]]; then
  if [[ -n "${CWS_PROFILES:-}" ]]; then CWS_CLAUDE_HOMES="${(j: :)${(@)${=CWS_PROFILES}/#/$HOME/.claude-}}"
  else CWS_CLAUDE_HOMES="$HOME/.claude"; fi
fi
: ${CWS_TICKET_EXAMPLE:="PROJ-123"}
# Seed vocabulary for a session's task type; what you actually use is learned from
# past sessions and suggested first.
: ${CWS_TASK_TYPES:="permissions, job errors, new features, security, investigation, data quality, tooling, documentation"}

# claude-resume [--] [claude args...]: Claude Code, resuming by default. Everything goes to
# claude unchanged; with nothing it adds --resume, which opens the session picker. `--` ends
# claude-resume's options, for claude's own -p (print mode). CLAUDE_CONFIG_DIR is whatever
# this shell has (claude-search prints the right one with each session).
claude-resume() {
  emulate -L zsh
  case "$1" in
    -h|--help)
      print -r -- 'claude-resume [--] [claude args...]'
      print -r -- '    run Claude Code; no claude args: --resume, i.e. pick a session to resume'
      return 0 ;;
  esac
  [[ "$1" == -- ]] && shift
  (( $# )) || set -- --resume
  command claude "$@"
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

# --- suggestions -------------------------------------------------------------------
# claude-search --suggest: ticket candidates from the Jira cache and a task type from past
# requests. Prints tab-separated lines (nothing when there is nothing or it fails):
#   T<US>key<US>status<US>summary<US>strong(0|1)   up to 3, best first
#   Y<US>type<US>count     (US: the unit separator, \x1f)
_CWS_HERE="${${(%):-%x}:A:h}"
_cws_suggest() {
  local bin="$_CWS_HERE/../bin/claude-search"
  [[ -x $bin ]] || bin="$(command -v claude-search 2>/dev/null)"
  [[ -n $bin ]] || return 0
  "$bin" --suggest --json "$1" 2>/dev/null | "$CWS_PYTHON" -c '
import json, sys
try:
    d = json.load(sys.stdin)
except ValueError:
    sys.exit(0)
clean = lambda x: " ".join(str(x).split())
for c in d.get("tickets") or []:
    print("\x1f".join(["T", c["key"], clean(c["status"]), clean(c["summary"]), "1" if c.get("strong") else "0"]))
if d.get("type"):
    print("\x1f".join(["Y", clean(d["type"]["name"]), str(d["type"]["count"])]))
' 2>/dev/null
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
# <home>/projects/<folder path with non-alphanumerics as dashes>/, for one of CWS_CLAUDE_HOMES.
_cws_session_id() {
  "$CWS_PYTHON" - "$1" "$CWS_CLAUDE_HOMES" <<'PYEOF'
import glob, os, re, sys
folder, homes = sys.argv[1], sys.argv[2].split()
enc = re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(folder))
best, when = "", -1.0
for h in homes:
    for f in glob.glob(os.path.join(os.path.expanduser(h), "projects", enc, "*.jsonl")):
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

  WS_SID="$sid" WS_SCOPE="$scope" WS_TYPE="${(j: :)@}" WS_SET="$#" \
    WS_TASK_TYPES="$(_cws_task_types)" WS_REQUEST_TYPES="${CWS_TYPES:-}" "$CWS_PYTHON" - "$meta" <<'PYEOF'
import json, os, sys
p = sys.argv[1]
if os.environ["WS_SET"] != "0":
    new = os.environ["WS_TYPE"].strip()
    known = [t.strip() for t in os.environ["WS_TASK_TYPES"].splitlines() if t.strip()]
    if known and new.lower() not in [k.lower() for k in known]:
        msg = "claude-type: '{}' is not a task type ({})".format(new, ", ".join(known))
        if new.lower() in os.environ["WS_REQUEST_TYPES"].lower().split():
            msg += "\n  '{}' is a request type: run claude-area --type {}".format(new, new.lower())
        print(msg, file=sys.stderr)
        raise SystemExit(1)
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

# claude-goal ["GOAL"] [--done "TEXT"]   show or re-anchor the session folder's goal
# Use it when the objective changes on purpose; claude-guard then judges new prompts
# against the new goal, from a fresh scope. The old goal is kept in goal_history.
claude-goal() {
  emulate -L zsh
  local dir="$PWD" meta="" goal="" done_when="" has_done=0
  local -a paths=()
  while (( $# )); do
    case "$1" in
      --done) done_when="$2"; has_done=1; shift 2 ;;
      --path)
        if [[ -z "$2" || ! -d "${~2}" ]]; then print -u2 -- "claude-goal: --path needs an existing folder"; return 1; fi
        paths+=("${${~2}:A}"); shift 2 ;;
      -h|--help) print -r -- 'claude-goal ["GOAL"] [--done "TEXT"] [--path DIR]...   show or change the session goal and scope'; return 0 ;;
      *) goal="${goal:+$goal }$1"; shift ;;
    esac
  done
  while [[ "$dir" == "$CLAUDE_WORK_ROOT"/* ]]; do
    if [[ -f "$dir/.session.json" ]]; then meta="$dir/.session.json"; break; fi
    dir="${dir:h}"
  done
  if [[ -z "$meta" ]]; then
    print -u2 -- "claude-goal: no .session.json here (not inside a session folder)"; return 1
  fi
  WS_GOAL="$goal" WS_DONE="$done_when" WS_HAS_DONE="$has_done" WS_PATHS="${(pj:\n:)paths}" "$CWS_PYTHON" - "$meta" <<'PYEOF'
import datetime, json, os, sys
p = sys.argv[1]
d = json.load(open(p))
old, old_done = d.get("goal") or d.get("name") or "", d.get("done_when") or ""
goal, has_done = os.environ["WS_GOAL"].strip(), os.environ["WS_HAS_DONE"] == "1"
new_paths = [p for p in os.environ["WS_PATHS"].split("\n") if p]
if new_paths:                                 # more scope, same goal: no re-anchoring
    have = d.get("paths") if isinstance(d.get("paths"), list) else []
    d["paths"] = have + [p for p in new_paths if p not in have]
    json.dump(d, open(p, "w"), indent=2)
    print("paths: " + ", ".join(d["paths"]))
    if not goal and not has_done:
        raise SystemExit(0)
if not goal and not has_done:
    print("goal: {}\ndone when: {}".format(old or "(none)", old_done or "(not stated)"))
    if d.get("paths"):
        print("paths: " + ", ".join(d["paths"]))
    raise SystemExit(0)
ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
d.setdefault("goal_history", []).append({"goal": old, "done_when": old_done, "until": ts})
d["goal"] = goal or old
if has_done:
    d["done_when"] = os.environ["WS_DONE"].strip()
json.dump(d, open(p, "w"), indent=2)
folder = os.path.dirname(p)
# a new goal starts a fresh scope: the next prompt defines it again
sp = os.path.join(folder, ".scope.json")
try:
    s = json.load(open(sp))
    for st in (s.get("sessions") or {}).values():
        for k in ("literal", "targets", "open", "extensions", "recent"):
            st.pop(k, None)
    json.dump(s, open(sp, "w"), indent=1)
except (OSError, ValueError, AttributeError):
    pass
with open(os.path.join(folder, ".quality.jsonl"), "a") as fh:
    fh.write(json.dumps({"ts": ts, "event": "goal", "initiated_by": "user", "decision": "allow", "type": "ok",
                         "reason": "re-anchored", "goal": d["goal"], "previous": old}, ensure_ascii=False) + "\n")
print("goal: {} -> {}".format(old or "(none)", d["goal"]))
if has_done:
    print("done when: {}".format(d["done_when"] or "(not stated)"))
PYEOF
}

# claude-wait [me|them|none] ["WHO"] ["WHAT"] [--where teams|mail|jira] [--link URL] [--since DATE] [--note TEXT]
#   show or set who this request is waiting on; the VS Code sidebar's Open topics view lists it
#   under "Waiting on me" or "Waiting on someone". none clears it. Every change is logged in
#   the folder's thread.md, with --note's text (where things stand) under it.
claude-wait() {
  emulate -L zsh
  local dir="$PWD" meta="" on="" who="" what="" where="" link="" since="" note=""
  local -a rest=()
  while (( $# )); do
    case "$1" in
      --where) where="$2"; shift 2 ;;
      --link)  link="$2";  shift 2 ;;
      --since) since="$2"; shift 2 ;;
      -n|--note) note="$2"; shift 2 ;;
      -h|--help)
        print -r -- 'claude-wait [me|them|none] ["WHO"] ["WHAT"] [--where teams|mail|jira] [--link URL] [--since DATE] [--note TEXT]   show or set who the request waits on; the note goes to thread.md'
        return 0 ;;
      *) rest+=("$1"); shift ;;
    esac
  done
  if (( ${#rest} )); then
    case "${rest[1]:l}" in
      me|mine)            on="me" ;;
      them|other|others)  on="other" ;;
      none|clear|nobody)  on="none" ;;
      *) print -u2 -- "claude-wait: first argument must be me, them or none"; return 1 ;;
    esac
    who="${rest[2]:-}"; what="${(j: :)rest[3,-1]}"
  fi
  while [[ "$dir" == "$CLAUDE_WORK_ROOT"/* ]]; do
    if [[ -f "$dir/.session.json" ]]; then meta="$dir/.session.json"; break; fi
    dir="${dir:h}"
  done
  if [[ -z "$meta" ]]; then
    print -u2 -- "claude-wait: no .session.json here (not inside a session folder)"; return 1
  fi
  WS_ON="$on" WS_WHO="$who" WS_WHAT="$what" WS_WHERE="$where" WS_LINK="$link" WS_SINCE="$since" WS_NOTE="$note" \
    "$CWS_PYTHON" - "$meta" <<'PYEOF'
import datetime, json, os, sys
p = sys.argv[1]
d = json.load(open(p))
old = d.get("waiting") if isinstance(d.get("waiting"), dict) and d["waiting"].get("on") in ("me", "other") else None

def show(w):
    if not w:
        return "waiting: nobody"
    return "waiting on {}: {}{}{}{}".format(
        "me" if w["on"] == "me" else "them", w.get("who") or "?",
        " -- " + w["what"] if w.get("what") else "", " (" + w["where"] + ")" if w.get("where") else "",
        " since " + w["since"][:10] if w.get("since") else "")

on = os.environ["WS_ON"]
thread = os.path.join(os.path.dirname(p), "thread.md")
if not on:
    print(show(old))
    if os.path.exists(thread):
        print("thread.md: {} entries".format(open(thread).read().count("\n## ")))
    raise SystemExit(0)
now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
if old:
    d.setdefault("waiting_history", []).append(dict(old, until=now))
if on == "none":
    d.pop("waiting", None)
else:
    who, what = os.environ["WS_WHO"].strip(), os.environ["WS_WHAT"].strip()
    keep = old or {}
    d["waiting"] = {"on": on, "who": who or keep.get("who", ""), "what": what or keep.get("what", ""),
                    "since": os.environ["WS_SINCE"].strip() or now,
                    "where": os.environ["WS_WHERE"].strip() or keep.get("where", ""),
                    "link": os.environ["WS_LINK"].strip() or keep.get("link", "")}
json.dump(d, open(p, "w"), indent=2)
# the change, and the note, go to thread.md: the context the next session starts from
w = d.get("waiting")
head = "## {} · {}".format(now[:16].replace("T", " "), "settled" if not w else show(w).replace(" since " + w["since"][:10], ""))
note = os.environ["WS_NOTE"].strip()
with open(thread, "a") as fh:
    if fh.tell() == 0:
        fh.write("# {}\n\nWho said what, in order. claude-inbox adds the messages it finds; claude-wait --note adds yours.\n\n".format(d.get("name") or os.path.basename(os.path.dirname(p))))
    fh.write(head + "\n\n" + (note + "\n\n" if note else ""))
print("{} -> {}".format(show(old), show(w)))
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

# Request folders on TICKET from the last DAYS days, newest first: "path<TAB>relative  name  (age)".
_cws_recent_folders() {
  WS_TICKET="$1" WS_DAYS="$2" WS_ROOT="$CLAUDE_WORK_ROOT" "$CWS_PYTHON" - <<'PYEOF'
import datetime, glob, json, os
root, ticket, days = os.environ["WS_ROOT"], os.environ["WS_TICKET"].upper(), int(os.environ["WS_DAYS"])
cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y/%m/%d")
out = []
for meta in sorted(glob.glob(os.path.join(root, "[0-9]" * 4, "[0-9][0-9]", "[0-9][0-9]", "*", ".session.json")), reverse=True)[:400]:
    folder = os.path.dirname(meta)
    rel = os.path.relpath(folder, root).replace(os.sep, "/")
    if rel[:10] < cutoff:
        break
    try:
        d = json.load(open(meta))
    except (OSError, ValueError):
        continue
    if (d.get("ticket") or "").strip().upper() != ticket:
        continue
    try:
        when = datetime.datetime.strptime(rel[:19], "%Y/%m/%d/%H-%M-%S")
        age = (datetime.date.today() - when.date()).days   # calendar days, not 24-hour blocks
        age = "today" if age == 0 else "{}d ago".format(age)
    except ValueError:
        age = "?"
    out.append("{}\t{}  {}  ({})".format(folder, rel, d.get("name") or "", age))
    if len(out) == 5:
        break
print("\n".join(out))
PYEOF
}

# How a request is opened, and what runs just before: two command templates in config.env.
#   CWS_OPEN_CMD       opens the folder (T3, an editor, a terminal...); empty = print its path
#   CWS_AFTER_NEW_CMD  runs once the folder exists, before it is opened (T3's sidebar grouping)
# Placeholders {dir} {title} {prompt} {project} {type} are replaced by shell-quoted values, so
# each one stays one argument however many spaces or quotes it holds. A config from before 3.1
# has neither line: CWS_OPEN="t3" then means T3's command, and claude-area, when installed,
# placed every request, so those are what a missing line means.
_cws_open_cmd() {
  if (( ${+CWS_OPEN_CMD} )); then print -r -- "$CWS_OPEN_CMD"
  elif [[ "${CWS_OPEN:-}" == t3 ]]; then print -r -- 'claude-t3-sync --open {dir} --prompt {prompt}'
  fi
}
_cws_after_new_cmd() {
  if (( ${+CWS_AFTER_NEW_CMD} )); then print -r -- "$CWS_AFTER_NEW_CMD"
  elif command -v claude-area >/dev/null 2>&1; then print -r -- 'claude-area --dir {dir} --pick {project} --type {type}'
  fi
}
# _cws_run_template TEMPLATE DIR TITLE PROMPT PROJECT TYPE: fill it in and run it
_cws_run_template() {
  local cmd="$1"
  cmd="${cmd//\{dir\}/${(q)2}}"
  cmd="${cmd//\{title\}/${(q)3}}"
  cmd="${cmd//\{prompt\}/${(q)4}}"
  cmd="${cmd//\{project\}/${(q)5}}"
  cmd="${cmd//\{type\}/${(q)6}}"
  eval "$cmd"
}

# Open an existing request folder again, through CWS_OPEN_CMD.
_claude_new_continue() {
  local dir="$1" prompt="$2" title open
  title="$(WS_DIR="$dir" "$CWS_PYTHON" -c 'import json,os
try: print(json.load(open(os.path.join(os.environ["WS_DIR"], ".session.json"))).get("name") or "")
except Exception: print("")')"
  print -r -- "→ continuing in ${dir#$CLAUDE_WORK_ROOT/}"
  cd "$dir" || return 1
  open="$(_cws_open_cmd)"
  if [[ -z "$open" ]]; then print -r -- "$dir"; return 0; fi
  _cws_run_template "$open" "$dir" "${title:-${dir:t}}" "$prompt" "" ""
}

claude-new() {
  emulate -L zsh
  setopt local_options no_nomatch

  local name="" ticket="" canon="" dir slug started audit=1 ask_audit=1 ttype="" prompt="" fresh=0
  local goal="" done_when="" goal_set=0 project="" front="" open after
  local -a paths=()

  while [[ "$1" == -* ]]; do
    case "$1" in
      -n|--no-audit) audit=0;          shift ;;
      -a|--audit)    ask_audit=0;      shift ;;
      --prompt)
        if [[ -z "$2" ]]; then print -u2 -- "claude-new: --prompt needs the text to start Claude with"; return 1; fi
        prompt="$2"; shift 2 ;;
      --new) fresh=1; shift ;;
      -T|--type)     ttype="$2";       shift 2 ;;
      -A|--project)  project="$2";     shift 2 ;;
      -F|--front)    front="$2";       shift 2 ;;
      -g|--goal)     goal="$2"; goal_set=1; shift 2 ;;
      --done)        done_when="$2";   shift 2 ;;
      --path)
        if [[ -z "$2" || ! -d "${~2}" ]]; then print -u2 -- "claude-new: --path needs an existing folder"; return 1; fi
        paths+=("${${~2}:A}"); shift 2 ;;
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
print("{:<14} {:<16} {:<9}".format(d.get("ticket") or "-",
                                  (d.get("task_type") or "-")[:16],
                                  "no-audit" if d.get("audit") is False else ""))' "$meta" 2>/dev/null)
          printf '  %s %s\n' "$info" "${d#$CLAUDE_WORK_ROOT/}"
        done
        return 0 ;;
      -h|--help)
        print -r -- 'claude-new [-n|-a] [-t TICKET] [-T TYPE] [-A PROJECT] [-F TYPE] [-g GOAL] [--done TEXT] [--path DIR]... [--prompt TEXT] [name]'
        print -r -- '    create a YYYY/MM/DD/HH-mm-ss_slug folder, then open it with CWS_OPEN_CMD'
        print -r -- "    (now: ${$(_cws_open_cmd):-nothing, the folder path is printed})"
        print -r -- '    --prompt TEXT is the first prompt, e.g. --prompt /weekly-review: {prompt} in CWS_OPEN_CMD'
        print -r -- "    TICKET is mandatory: PREFIX-123 (e.g. $CWS_TICKET_EXAMPLE), or Other"
        print -r -- '    -T / --type is the kind of work (permissions, job errors, ...); asked if omitted'
        print -r -- '    -A / --project and -F / --front place it in T3 (CWS_PROJECTS, CWS_TYPES): {project} and {type}'
        print -r -- '    in CWS_AFTER_NEW_CMD; chosen from the context if omitted'
        print -r -- '    -g / --goal is what the session should deliver, --done how you will know it did;'
        print -r -- '    both asked if omitted (Enter: the name / nothing). claude-guard keeps work on them'
        print -r -- '    --path DIR (repeatable): a folder or repo outside the request that is part of the work'
        print -r -- '    -n / --no-audit keeps the session out of claude-audit and the weekly review'
        print -r -- '    (claude-search still finds it); -a / --audit keeps it in; asked if neither'
        print -r -- '    --new always makes a new folder: no offer to continue in a recent one on the same ticket'
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

  # Suggestions from the Jira cache and past requests: asked with, never blocking. Only where a
  # question is asked (a terminal), or for a hint when -t Other was given.
  local -a sugg=() cand=() f=()
  local sline stype="" scount=0 ticket_given=0
  [[ -n "$ticket" ]] && ticket_given=1
  if [[ ( -t 0 && ( -z "$ticket" || -z "$ttype" ) ) || "${ticket:l}" == other ]]; then
    sugg=("${(@f)$(_cws_suggest "$name $goal")}")
    sugg=("${(@)sugg:#}")
    for sline in $sugg; do
      case "${sline[1]}" in
        T) cand+=("$sline") ;;
        Y) f=("${(@ps:\x1f:)sline}"); stype="${f[2]}"; scount="${f[3]}" ;;
      esac
    done
  fi
  if [[ "${ticket:l}" == other ]] && (( ${#cand} )); then
    f=("${(@ps:\x1f:)cand[1]}")
    [[ "${f[5]}" == 1 ]] && print -u2 -- "hint: maybe ${f[2]} — ${f[4]}"
  fi

  while true; do
    if [[ -z "$ticket" ]]; then
      local dflt="" n=1
      if (( ${#cand} )); then
        print -r -- ""
        print -r -- "  Ticket candidates (a number, a ticket, or Other; Enter for the one in brackets):"
        for sline in $cand; do
          f=("${(@ps:\x1f:)sline}")
          printf '    %d) %s  %s  [%s]\n' $n "${f[2]}" "${f[4]}" "${f[3]}"
          (( n++ ))
        done
        # Enter takes the top candidate only when it is strong; otherwise it means Other.
        f=("${(@ps:\x1f:)cand[1]}")
        if [[ "${f[5]}" == 1 ]]; then dflt="${f[2]}"; else dflt="Other"; fi
      fi
      read "ticket?Jira ticket${dflt:+ [$dflt]} (e.g. $CWS_TICKET_EXAMPLE, or Other): " || return 1
      if [[ -n "$dflt" && -z "${ticket//[[:space:]]/}" ]]; then
        ticket="$dflt"
      elif [[ "$ticket" == <-> ]] && (( ticket >= 1 && ticket <= ${#cand} )); then
        ticket="${${(@ps:\x1f:)cand[$ticket]}[2]}"
      fi
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

  # A ticket that already has a request folder from the last two weeks: continue there
  # instead of starting a fourth folder for the same work. --new skips the offer.
  if (( ! fresh )) && [[ -t 0 && "$ticket" != "Other" ]]; then
    local -a recent=("${(@f)$(_cws_recent_folders "$ticket" 14)}")
    recent=("${(@)recent:#}")
    if (( ${#recent} )); then
      print -r -- ""
      print -r -- "$ticket has recent request folders:"
      local i=1 line
      for line in $recent; do
        printf '  %d) %s
' $i "${line#*$'	'}"
        (( i++ ))
      done
      printf '  %d) a new folder
' $i
      local go=""
      read "go?Continue in [1]: " || return 1
      go="${go:-1}"
      if [[ "$go" == <-> ]] && (( go >= 1 && go <= ${#recent} )); then
        dir="${${recent[$go]}%%$'	'*}"
        _claude_new_continue "$dir" "$prompt"
        return
      elif [[ "$go" != "$i" ]]; then
        print -u2 -- "claude-new: invalid choice '$go'"; return 1
      fi
    fi
  fi

  # Task type: what kind of work this is. Suggested from the name, chosen from what
  # you have used before, or typed fresh.
  if [[ -z "$ttype" ]]; then
    local -a types=("${(@f)$(_cws_task_types)}")
    local guess="$(_cws_guess_type "$name")" pick="" i=1 t tries=0
    if [[ -t 0 ]]; then
      print -r -- ""
      # What past requests like this one were: it beats the keyword guess when it exists.
      if [[ -n "$stype" ]]; then
        guess="$stype"
        print -r -- "  Suggested: $stype ($scount similar request$([[ $scount == 1 ]] || print -rn s))"
      fi
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

  # Goal and done-when: the contract claude-guard holds the session to. Asked only with
  # CWS_ASK_GOAL="1"; otherwise the name is the goal and claude-goal changes it later.
  if (( ! goal_set )) && (( ${CWS_ASK_GOAL:-0} )) && [[ -t 0 ]]; then
    read "goal?Goal — what should this session deliver? [$name]: " || return 1
    [[ -z "$done_when" ]] && { read "done_when?Done when (Enter to skip): " || return 1; }
  fi
  [[ -z "${goal//[[:space:]]/}" ]] && goal="$name"

  # Audit: whether the weekly review and daily recap count this session. Asked unless
  # -n or -a said; Enter keeps it in, as does running without a terminal.
  if (( audit && ask_audit )) && [[ -t 0 ]]; then
    local inc=""
    read "inc?Count it in the weekly review and daily recap? [Y/n]: " || return 1
    [[ "${inc:l}" == n* ]] && audit=0
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
  WS_NAME="$name" WS_TICKET="$ticket" WS_SLUG="$slug" WS_TYPE="$ttype" \
  WS_STARTED="$started" WS_DIR="$dir" WS_AUDIT="$audit" WS_GOAL="$goal" WS_DONE="$done_when" \
  WS_PATHS="${(pj:\n:)paths}" \
    "$CWS_PYTHON" -c '
import json, os, socket
p = os.path.join(os.environ["WS_DIR"], ".session.json")
json.dump({
    "name":       os.environ["WS_NAME"],
    "slug":       os.environ["WS_SLUG"],
    "ticket":     os.environ["WS_TICKET"],
    "task_type":  os.environ.get("WS_TYPE", ""),
    "goal":       os.environ["WS_GOAL"],
    "done_when":  os.environ["WS_DONE"],
    "paths":      [p for p in os.environ["WS_PATHS"].split("\n") if p],
    "audit":      os.environ["WS_AUDIT"] == "1",
    "started_at": os.environ["WS_STARTED"],
    "ended_at":   None,
    "host":       socket.gethostname(),
    "path":       os.environ["WS_DIR"],
}, open(p, "w"), indent=2)
'

  print -r -- "→ $ticket  ${ttype:+[$ttype]  }${dir#$CLAUDE_WORK_ROOT/}${${audit:#1}:+  (no-audit)}"
  cd "$dir" || return 1

  # What runs once the folder exists (T3's sidebar placement, before T3 first sees the folder: it
  # caches a project's repository for 15 minutes), then what opens it. Nothing waits for the app,
  # so ended_at stays empty.
  after="$(_cws_after_new_cmd)"
  [[ -n "$after" ]] && { _cws_run_template "$after" "$dir" "$name" "$prompt" "$project" "$front" || true; }
  open="$(_cws_open_cmd)"
  if [[ -z "$open" ]]; then print -r -- "$dir"; return 0; fi
  _cws_run_template "$open" "$dir" "$name" "$prompt" "$project" "$front"
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

# Open a file or folder with the desktop's default app: Finder / Explorer / xdg-open.
# CWS_OS (mac, linux, wsl) overrides the detection, for tests.
_cws_open() {
  local os="$CWS_OS"
  if [[ -z "$os" ]]; then
    if [[ "$(uname -s)" == Darwin ]]; then os=mac
    elif grep -qsi microsoft /proc/version; then os=wsl
    else os=linux; fi
  fi
  case $os in
    mac) open "$1" ;;
    wsl) (cd /mnt/c 2>/dev/null; explorer.exe "$(wslpath -w "$1")"); return 0 ;;  # explorer.exe exits 1 on success
    *)   xdg-open "$1" >/dev/null 2>&1 &! ;;
  esac
}

# ws: fuzzy-pick a request folder (newest first) and cd into it
#   ws -o  also open in Finder / Explorer · ws -c  also open in VS Code · ws -y  also browse with yazi
ws() {
  local root="$CLAUDE_WORK_ROOT" d
  d=$(cd "$root" && print -rl -- [0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9]/*(/On) | fzf --height=60% --reverse \
        --preview "ls -la $root/{}") || return
  cd "$root/$d" || return
  case $1 in
    -o) _cws_open . ;;
    -c) code . ;;
    -y) y ;;
  esac
}
