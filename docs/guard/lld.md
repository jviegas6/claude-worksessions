# claude-guard — Low-Level Design

| | |
|---|---|
| Component | `bin/claude-guard`, the `claude-new` / `claude-goal` changes in `shell/worksessions.zsh`, hook registration in `install.sh` / `uninstall.sh` |
| Version | claude-worksessions 2.16.0 |
| Companion documents | [High-Level Design](hld.md) · [User guide](user-guide.md) |
| Part of | claude-worksessions: [HLD](../hld.md) · [LLD](../lld.md) |

This document describes the implementation as it is. Names in `code` are the identifiers
in `bin/claude-guard` unless stated otherwise.

---

## 1. Module layout

`bin/claude-guard` is a single Python 3 script with no dependencies outside the standard
library (`contextlib`, `datetime`, `hashlib`, `json`, `os`, `re`, `subprocess`, `sys`,
`tempfile`, `time`, `fcntl`). It is installed as a symlink at `~/.local/bin/claude-guard`.

| Section | Functions |
|---|---|
| Configuration | `load_config`, `settings`, `now` |
| Session folder and state | `session_dir`, `read_json`, `session_goal`, `scope` (context manager), `log` |
| Identifier extraction | `strings`, `anchors`, `prompt_anchors`, `matches`, `safe_roots`, `safe`, `reached`, `trivial` |
| Judge | `rules_text`, `judge_profile`, `judge`, `grow`, `apply_verdict` |
| Hooks | `on_prompt`, `on_tool`, `deny`, `on_stop`, `new_turn` |
| Journal and review | `journal_dir`, `decision_id`, `journal`, `read_jsonl`, `reviews`, `review` |
| Report | `report` |
| Entry point | `HOOKS`, `main` |

### 1.1 Command-line dispatch (`main`)

```
claude-guard prompt | tool | stop        hook mode: JSON payload on stdin, JSON answer on stdout
claude-guard judge <session-dir> <job>   internal: background judge for shadow mode
claude-guard report [--days N] [PATH]    human report
claude-guard review [--days N] [--all]   list judge decisions to review
claude-guard review ID right|wrong [NOTE…]   mark one decision
claude-guard -h | --help                 usage on stderr, exit 0
claude-guard <anything else>             usage on stderr, exit 1
```

Order of evaluation in `main`:

1. `cfg = settings(load_config())`. Configuration is read on every invocation, so a mode
   change applies to the next hook call without a restart.
2. `report` → `report(argv[1:], cfg, stdout)`; `review` → `review(argv[1:], cfg, stdout)`.
3. `judge` → `apply_verdict(argv[1], json.loads(argv[2]), cfg, *judge(job, cfg))`, exit 0.
4. Unknown sub-command → usage.
5. **Silence rules:** if the environment has `CWS_GUARD_JUDGE` set (we are inside the
   judge's own Claude process) or `cfg["mode"] == "off"`, exit 0 with no output.
6. `payload = json.load(stdin)`. A payload that is not a dict yields no answer.
7. `HOOKS[cmd](payload, cfg)`. **Any exception** is caught, reported on stderr as
   `claude-guard <cmd>: <Type>: <message>`, and the process exits 0 with no output (fail open).
8. A non-`None` answer is written to stdout as compact JSON. The exit code is always 0.

The hooks never use exit code 2. Blocking is done only through JSON, so Claude Code
treats every guard failure (a crash, a timeout, a non-zero exit) as non-blocking.

---

## 2. Configuration

### 2.1 `load_config()`

- Source: `$CWS_CONFIG`, else `~/.config/claude-worksessions/config.env`, which `install.sh`
  symlinks to `<work root>/_config/config.env`.
- Line format: `KEY=value`. Quoted values run up to the matching quote. Bare values drop a
  trailing ` # comment`. `$HOME` / `${HOME}` are expanded. Lines that don't match are ignored.
- Every `CWS_*` environment variable then overrides the file.
- A missing file gives an empty dict, and the defaults apply.

### 2.2 `settings(conf)` → `cfg`

| Key in `cfg` | Source | Default | Validation |
|---|---|---|---|
| `mode` | `CWS_GUARD_MODE` | `off` | lower-cased; anything outside `off`/`shadow`/`enforce` becomes `off` |
| `model` | `CWS_GUARD_MODEL` | `haiku` | passed as is to `claude --model` |
| `timeout` | `CWS_GUARD_JUDGE_TIMEOUT` | `15` | float; unparsable → 15.0 |
| `root` | `CWS_WORK_ROOT` → `$CLAUDE_WORK_ROOT` → `~/work_sessions` | — | `realpath` |
| `ignore` | `CODE_NAMES` ∪ `CWS_GUARD_IGNORE_NAMES` (space-separated, lower-cased) | `CODE_NAMES` | — |
| `profile` | `CWS_GUARD_PROFILE` | `""` (the session's own) | stripped; checked when the judge runs (§7.1) |

`CWS_GUARD_JUDGE_TIMEOUT` must stay below the hook timeout that `install.sh` registers for
`UserPromptSubmit` (30 s). Otherwise Claude Code kills the hook first, which is still
non-blocking, but nothing is logged.

---

## 3. Hook contracts

Fields not listed are ignored. The guard only needs the documented common fields plus the
event-specific ones below.

### 3.1 `UserPromptSubmit` → `claude-guard prompt`

Input used: `session_id`, `cwd`, `prompt`.

| Situation | stdout |
|---|---|
| shadow, or anything allowed without a scope | *(none)* |
| enforce, pivot | `{"decision": "block", "reason": "<message to the user>"}` |
| enforce, allowed with a literal scope | `{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "Scope of this request (claude-guard): <literal> Do exactly this. Where going further would help, end by proposing the next level instead of doing it."}}` |

The block `reason` is shown to the user and not added to Claude's context (per the spec).
It reads:

```
claude-guard: this looks like a new objective, not part of this session's goal (<judge reason>).
Session goal: <goal>
Start it in its own session (claude-new), re-anchor this one with claude-goal "..." if the goal
really changed, or resend it starting with force: to go ahead here.
```

### 3.2 `PreToolUse` → `claude-guard tool`

Registered with matcher `Read|Glob|Grep|WebFetch|WebSearch|Bash|mcp__.*`. The code checks the
tool name again against `REACH_TOOLS` (`^(Read|Glob|Grep|WebFetch|WebSearch|Bash|mcp__.*)$`),
so a broader registration is harmless.

Input used: `session_id`, `cwd`, `scratchpad_dir` (optional), `tool_name`, `tool_input`.

| Situation | stdout |
|---|---|
| shadow, or nothing to flag | *(none)* |
| enforce, loop or out of scope | `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "<reason for Claude>"}}` |

Reasons:

- loop: `claude-guard: this is the same <tool> call <n> times in this request. Change approach or ask the user instead of repeating it.`
- depth: `claude-guard: out of scope. This request is: <literal or "(see the prompt)"> -- and <up to 3 identifiers> is not among its targets. Don't open it now; list it as a possible next step.`

The top-level `decision` field is deprecated for `PreToolUse` and is not used.

### 3.3 `Stop` → `claude-guard stop`

Input used: `session_id`, `cwd`, `last_assistant_message`, `stop_hook_active`.

| Situation | stdout |
|---|---|
| shadow, or proposals present, or no investigation | *(none)* |
| enforce, investigation without proposals, first stop | `{"decision": "block", "reason": "claude-guard: before finishing, add a short closing list of what could be examined next (the next level of depth) and why -- as proposals, without doing it."}` |

`last_assistant_message` is used instead of reading `transcript_path`, which the spec says
may lag at Stop time.

---

## 4. Session folder resolution — `session_dir(cwd, root)`

```
d = realpath(cwd or ".")
while d == root or d starts with root + "/":
    if d/.session.json is a file: return d
    if d == root: break
    d = parent(d)
return None
```

- A session started in a sub-folder of a request folder is attributed to that request.
- The work root itself is never a request, even if a `.session.json` were there.
- Anything outside the root returns `None`. All three hooks then return `None` without
  touching the disk.

`session_goal(sdir)` reads `.session.json` and returns `(goal or name, done_when)`, both
stripped. A missing or corrupt file gives `("", "")`.

---

## 5. State — `.scope.json`

### 5.1 Schema

```json
{
 "sessions": {
  "<session_id>": {
   "prompt_no": 7,
   "literal": "List the sources of the orders model.",
   "targets": ["db.core.orders", "orders_model"],
   "open": false,
   "turn": {
    "reach": 4,
    "outside": ["db.staging.orders_raw"],
    "calls": {"3f9a1c0b2d4e": 1, "a01b2c3d4e5f": 3},
    "stopped": true
   }
  }
 }
}
```

| Field | Meaning | Written by |
|---|---|---|
| `prompt_no` | count of prompts seen in this session, trivial ones included | `on_prompt` |
| `literal` | one-sentence literal scope of the current request | judge result (`apply_verdict`); the text after `force:` |
| `targets` | sorted, lower-cased, de-duplicated names the session's requests are about. They **accumulate** over the session and are reset only by `claude-goal` | `grow` |
| `open` | "go deeper" was asked: target checks are off until the next non-trivial prompt | `grow`, `force:` |
| `turn.reach` | reading-tool calls in the current request (safe ones included) | `on_tool` |
| `turn.outside` | identifiers already flagged in this request (for de-duplication and the stop summary) | `on_tool` |
| `turn.calls` | `sha1(tool_name + json(tool_input, sort_keys))[:12]` → count | `on_tool` |
| `turn.stopped` | a Stop was already evaluated for this request | `on_stop` |

A session id missing from the payload is stored under `"none"`.

### 5.2 Locking — `scope(sdir, sid)`

A context manager that:

1. `os.open(".scope.json", O_RDWR | O_CREAT, 0o644)`, `fdopen("r+")`.
2. `fcntl.flock(LOCK_EX)`, which blocks until other writers finish.
3. Parses the content. An empty, unparsable or non-dict file becomes `{}`.
4. Yields the session's dict (created if missing).
5. On exit: `seek(0)`, `truncate()`, writes the whole document (`indent=1`, UTF-8), and the
   lock is released on close.

All read-modify-write of state happens inside this block. Logging (`log`) happens after it,
so the lock is held for microseconds.

### 5.3 Log — `.quality.jsonl`

`log(sdir, record)` appends `{"ts": <UTC ISO-8601 Z>, **record}` as one line (`ensure_ascii=False`).
If the file can't be written, a message goes to stderr and the hook carries on.

Common fields: `ts`, `event`, `session_id`, `initiated_by`, `mode`, `decision`, `type`, `reason`.

| `event` | `type` | `decision` | Extra fields | When |
|---|---|---|---|---|
| `prompt` | `ok` | `allow` | `prompt_no`, `prompt`, `override: true` | prompt starts with `force:` |
| `prompt` | `ok` | `allow` | `prompt_no`, `prompt`, `widened: true` | prompt asks to go deeper (logged before the verdict) |
| `prompt` | `ok` / `pivot` | `allow` / `block` | `prompt_no`, `prompt` (≤200), `judge_ms`, `verdict`, `literal` (≤300), `targets`, `reason` (≤400) | judge answered |
| `prompt` | `ok` | `allow` | `prompt_no`, `prompt`, `judge_ms`, `judge_error: true` | judge failed or timed out |
| `prompt` | `ok` | `allow` | `prompt_no`, `prompt`, `judge_error: true` | shadow: background judge could not be started |
| `tool` | `loop` | `deny` | `prompt_no`, `tool` | the `LOOP_AFTER`th identical call (logged once) |
| `tool` | `depth` | `deny` | `prompt_no`, `tool`, `reached` (≤5), `targets` (≤20) | new out-of-scope identifiers |
| `stop` | `ok` / `depth` | `allow` / `block` | `prompt_no`, `reach`, `outside` (count), `retry` | every evaluated Stop |
| `goal` | `ok` | `allow` | `goal`, `previous` | `claude-goal` re-anchored (written by the shell) |

`initiated_by` is `user` for `prompt` and `goal`, and `agent` for `tool` and `stop`.
`decision` is always what enforce does or would do, whatever the mode. Trivial prompts are
not logged.

---

## 6. Prompt pipeline — `on_prompt`

```
sdir = session_dir(cwd, root); none → return
goal, done_when = session_goal(sdir)
with scope(sdir, sid) as st:
    st.prompt_no += 1 → no
    literal = st.literal                                    # scope *before* this prompt
    if FORCE matches:                                       # ^\s*force:\s*  (case-insensitive)
        st.open = True; st.turn = new; st.literal = prompt minus prefix (≤300)
        log override; return None
    if trivial(prompt):
        st.turn = new; return None                          # same request continues
    st.turn = new
    widen = WIDEN matches; names = prompt_anchors(prompt)
    if mode == shadow: grow(st, names, widen)              # counts at once
    if widen: log widened
job = {sid, no, prompt, goal, done_when, literal, names, widen}
if mode == shadow:
    Popen([python, this file, "judge", sdir, json(job)], stdin/out/err=DEVNULL, start_new_session=True)
    (OSError → log judge_error)
    return None
rec = apply_verdict(sdir, job, cfg, *judge(job, cfg))      # enforce: synchronous
block if rec.decision == block; else additionalContext if rec.literal; else None
```

### 6.1 `trivial(prompt)`

Returns `True`, meaning no judge call and the request continues, when:

1. the prompt is empty or starts with `/` (slash command), `<` (tool/command echo) or `[`; or
2. it asks for nothing new: it does **not** match `WIDEN`, names nothing (`prompt_anchors`
   is empty), and either
   - matches `CONFIRM` (yes, ok, go ahead, done, merged, thanks, continue, proceed, sim,
     avança, segue, faz, pode ser, …) with at most 6 words, or
   - has fewer than 3 words and no `?`.

| Prompt | trivial | why |
|---|---|---|
| `yes` / `ok go ahead` / `sim, faz` | yes | confirmation |
| `merge it` | yes | < 3 words |
| `why?` | no | a question |
| `check db.core` | no | names something |
| `go deeper into the lineage` | no | asks to widen |

### 6.2 Widening

`WIDEN`: `aprofund*`, `mais a fundo`, `mais fundo`, `explora*`/`explore*`, `go deeper`,
`dig deeper`, `dig into`, `deep dive`/`deep-dive`, `in depth`, `explore`, `expand on`
(case-insensitive, word-bounded). It sets `open = True` for the request, and the next
non-trivial prompt sets it back to its own `widen` value.

### 6.3 `grow(st, names, widen)`

`targets = sorted(targets ∪ {n.strip().lower() for n in names if n.strip()})`; `open = widen`.

### 6.4 When the scope changes

| Mode | Prompt's own names | Judge's targets and literal |
|---|---|---|
| shadow | at once, in `on_prompt` | in the background, if `prompt_no` is still the job's `no` |
| enforce, allowed | after the verdict, if still current | same |
| enforce, judge failed | after the failure, if still current | — |
| enforce, pivot | never | never |

The "still current" check (`st.prompt_no == job.no`) stops a slow verdict from overwriting
the scope of a newer request. The log line is written either way.

---

## 7. Judge

### 7.1 Invocation — `judge(job, cfg)`

```
claude -p
  --settings '{"disableAllHooks": true}'   # the profile's settings load (gateway URL/token), no hook runs
  --strict-mcp-config             # no MCP servers
  --model <cfg.model>
  --tools ""                      # no tools
  --no-session-persistence        # no transcript: stays out of the audit trail
  --system-prompt "<guard-rules.md or DEFAULT_RULES>\nAnswer only via the JSON schema."
  --output-format json
  --json-schema <SCHEMA>
  "<message>"
```

- `subprocess.run(..., capture_output=True, text=True, timeout=cfg.timeout, cwd=tempfile.gettempdir(), env=<judge_profile env>)`.
- **Profile — `judge_profile(cfg)` → `(name, env, error)`.** `env` is `os.environ` plus
  `CWS_GUARD_JUDGE=1`. With `cfg.profile` set, `CLAUDE_CONFIG_DIR` is replaced by
  `~/.claude-<profile>`. If that folder doesn't exist, the judge is not called and the
  result is the error `judge profile dir <path> not found` (fail open). With it unset, the
  inherited `CLAUDE_CONFIG_DIR` stays, and the name is its basename minus `.claude-`
  (`default` if unset).
- The working directory is the temp dir, so no project `CLAUDE.md` is picked up.
- By default `CLAUDE_CONFIG_DIR` is inherited from the hook's environment, so the judge uses
  the same profile, login and endpoint (API gateway) as the session. `CWS_GUARD_PROFILE`
  overrides it.
- `--bare` is **not** used: it skips the OAuth login that subscription profiles rely on
  (verified: "Not logged in").
- `--setting-sources ""` is **not** used either: it also drops the profile's `settings.json`,
  where a gateway profile keeps `ANTHROPIC_BASE_URL` and its token (verified: "Not logged in"
  on the gateway profile). Hooks are switched off with `disableAllHooks` instead.

### 7.2 Message

```
GOAL: <goal or "(none)">
DONE_WHEN: <done_when or "(not stated)">
CURRENT SCOPE: <literal before this prompt, or "(none -- this is the first request)">
NEW PROMPT: <prompt, first 4000 chars>
<if first: "This is the session's first request: it defines the scope, so the verdict is continuation.">
```

"First" means the session has no literal yet. The verdict is also forced to `continuation`
in code after the call, so a first prompt can never be a pivot.

### 7.3 Output schema

```json
{"type": "object", "required": ["verdict", "literal", "targets", "reason"],
 "properties": {
   "verdict": {"type": "string", "enum": ["continuation", "extension", "pivot"]},
   "literal": {"type": "string"},
   "targets": {"type": "array", "items": {"type": "string"}},
   "reason":  {"type": "string"}}}
```

The answer is read from `structured_output` in Claude Code's JSON result.

### 7.4 Result handling

| Condition | Returns |
|---|---|
| `is_error` true, `structured_output` missing or not a dict, or verdict outside the enum | `(None, result or stderr or "no answer" [≤200], ms)` |
| `TimeoutExpired` | `(None, "timeout after <n>s", ms)` |
| `OSError` (no `claude`), `ValueError` (stdout not JSON) | `(None, str(e) [≤200], ms)` |
| success | `(answer, None, ms)` |

### 7.5 `apply_verdict(sdir, job, cfg, ans, err, ms)`

1. `blocked = verdict == "pivot" and mode == "enforce"`.
2. Under the lock: `current = st.prompt_no == job.no`.
   - enforce, current, not blocked → `grow(st, job.names, job.widen)`.
   - no error, current, not blocked → `literal = ans.literal or old literal or prompt[:300]`;
     `grow(st, ans.targets, st.open)` (keeps the open flag).
3. Log to `.quality.jsonl`: error → `allow`/`ok` with `judge_error`; else `block`/`pivot` for a
   pivot, `allow`/`ok` otherwise, with `verdict`, `reason`, `literal`, `targets`. Every prompt
   record from the judge carries `judge_id`.
4. `journal(...)` appends the full decision to the central journal (§10a).

In shadow a pivot is not blocked, so its targets are merged like any other. The session
really does carry on with that work, and the tool checks should reflect it.

### 7.6 Rules — `rules_text(root)`

Reads `<root>/_config/guard-rules.md`. A missing or blank file falls back to `DEFAULT_RULES`.
The whole file is the system prompt, including any HTML comment at the top.
`install.sh` seeds it from `config/guard-rules.example.md`, which is `DEFAULT_RULES` plus a
header comment.

---

## 8. Identifier extraction

### 8.1 Patterns

| Name | Pattern (summary) | Notes |
|---|---|---|
| `URL` | `https?://[^\s'"`<>)]+` | trailing `.,;` stripped; URLs are removed from the text before the other patterns run |
| `DOTTED` | three dot-separated identifier parts, not preceded by `\w . / -`, not followed by `\w -` or `.\w` | `db.schema.table`; `a.b.c.py` is not taken as `a.b.c` |
| `PATH` | `~?/segment(/segment)*`, not preceded by `\w . : / ~ -`; a segment may contain spaces only when another `/` follows | `~/Repos/Some Folder/x` whole; `/a/b c` → `/a/b`. `~` expanded; trailing `/.,;:` stripped |
| two-part names (prompts only) | `x.y` not followed by `\w . -` | `db.schema` |
| snake_case (prompts only) | `\b[A-Za-z]\w*_\w+\b`, ≥ 5 chars, not a part of a name already found | `orders_daily`; `db_prod` alone is dropped when `db_prod.core` was found, since it would cover everything under it |

Exclusions for dotted names: a last part in `FILE_EXT` (`py md json jsonl txt csv yml yaml
sh zsh log html gz sql toml ts js tsx ipynb env xml png pdf zip tar`), or a first part in
`cfg.ignore` (`CODE_NAMES` = `os sys json re self dt datetime subprocess np pd math time
pathlib shutil io cls super string collections typing`, plus `CWS_GUARD_IGNORE_NAMES`).

Everything is lower-cased.

### 8.2 `anchors(text, ignore)` and `prompt_anchors(text)`

`anchors` = URLs ∪ dotted names ∪ paths (longer than 2 chars). `prompt_anchors` adds two-part
names and snake_case words. The asymmetry is deliberate: too many targets costs little (a
missed flag), while too many identifiers on the tool side costs false flags.

### 8.3 `reached(tool, tool_input, ignore)`

| Tool | Identifiers |
|---|---|
| `Read`, `Glob`, `Grep` | `file_path` or `path`, expanded and lower-cased; none if absent (e.g. a Grep in the cwd) |
| `WebFetch` | `url` |
| `WebSearch` | `"search: " + query` |
| `Bash` | `anchors(command)` |
| `mcp__*` | `anchors` of every string anywhere in `tool_input` (recursive over dicts and lists) |

### 8.4 Safe places — `safe_roots` / `safe`

Roots: the session folder, payload `cwd`, payload `scratchpad_dir`, `tempfile.gettempdir()`,
`/tmp`, `/private/tmp`, `/dev`, `$CLAUDE_CONFIG_DIR`, `~/.claude`, and every `~/.claude-*`.
All are `realpath`'d and lower-cased. An identifier is safe if it is a path (starts with `/`)
and either its literal form or its `realpath` equals a root or lies under one. This handles
`/tmp` → `/private/tmp` on macOS.

### 8.5 Matching — `matches(ident, targets)`

`tail` = the last `/` segment of the identifier, then its last `.` part. The identifier is on
target if **any** target `t` with `len(t) ≥ 3` satisfies one of:

- `t in ident` (a call on `db.core.orders` is on target `core`; a file under a target folder);
- `ident in t`;
- `len(tail) ≥ 3 and tail == last "." part of t`.

| Identifier | Targets | On target |
|---|---|---|
| `db.core.orders` | `["core"]` | yes (substring) |
| `/r/model/x.py` | `["/r/model"]` | yes (under the folder) |
| `a.b.orders` | `["orders"]` | yes (same last part) |
| `db.staging.orders_raw` | `["db.core.orders"]` | no |

---

## 9. Tool pipeline — `on_tool`

```
tool not in REACH_TOOLS → return
sdir none → return
key = sha1(tool + json(tool_input, sort_keys))[:12]
with scope(sdir, sid) as st:
    turn = st.turn (created if missing)
    turn.reach += 1
    turn.calls[key] += 1 → repeats
    idents = {i in reached(...) if not safe(i)}
    off = sorted(i not matching st.targets)   only if targets non-empty and not st.open
    new_off = off minus turn.outside;  turn.outside += new_off
if repeats >= LOOP_AFTER (3):
    log loop once (at exactly 3); return deny(...)       # enforce denies every repeat from 3 on
if off:
    if new_off: log depth (reached[:5], targets[:20])     # logged once per identifier per request
    return deny(...)                                      # enforce denies every out-of-scope call
return None
```

- **No targets means no check.** Until a request names something (or the judge returns
  targets), nothing is out of scope.
- An identifier is **logged** once per request, but in enforce **every** call that reaches it
  is denied, so retrying a denied call does not get it through.
- `deny(cfg, reason)` returns the deny JSON only in enforce, and `None` otherwise.

---

## 10. Stop pipeline — `on_stop`

```
sdir none → return
with scope: turn = st.turn or new; if not stop_hook_active: st.turn.stopped = True
if turn.stopped (already before this call) and not stop_hook_active: return   # nothing new since last stop
investigated = turn.reach >= 2
missing = investigated and not stop_hook_active
          and not (PROPOSALS in last 800 chars of last_assistant_message or it ends with "?")
type = depth if turn.outside or missing else ok
log stop (decision block if missing, reason lists "went outside the targets: …" and/or "no next-level proposals at the end")
enforce and missing → block JSON
```

`PROPOSALS` (case-insensitive): `next step`, `next level`, `could also`, `if you want`, `want me
to`, `shall i`, `should i`, `would you like`, `deeper`, `próxim*`, `posso `, `queres`, `quer que`,
`se quiseres`, `aprofund*`, `próximo passo`.

Loop safety: Claude Code sets `stop_hook_active` on the stop that follows a hook-forced
continuation. With it set, `missing` is false, so the guard blocks at most once per request.
Claude Code's own cap (8 consecutive continuations) is a second backstop.

---

## 10a. Judge journal and review

### Journal — `<work root>/_audit/guard/judge.jsonl`

`journal(sdir, job, cfg, ans, err, ms, blocked)` appends one line per judge call (success or
failure, any mode). The folder is created if missing. A write failure goes to stderr and the
hook carries on.

```json
{"id": "3fa9c1d2e0", "ts": "2026-09-26T21:57:12Z", "folder": "2026/09/26/10-00-00_x",
 "session_id": "…", "prompt_no": 2, "mode": "shadow", "model": "haiku", "profile": "work",
 "judge_ms": 7056, "goal": "…", "done_when": "…", "scope_before": "…", "prompt": "… (≤4000)",
 "enforced": false,
 "verdict": "pivot", "literal": "…", "targets": ["…"], "reason": "…"}
```

- `id` = `sha1(session_id | prompt_no | prompt)[:10]`. It is the same value as `judge_id` in
  the folder's `.quality.jsonl`, so the two can be joined.
- `enforced` is true only when the decision blocked the prompt (a pivot in enforce).
- A failed call has `error` instead of `verdict`, `literal`, `targets` and `reason`.
- `scope_before` is the literal the judge was shown as the current scope. `prompt` is kept up
  to the 4,000 characters the judge saw (the folder log keeps 200).

### Reviews — `<work root>/_audit/guard/reviews.jsonl`

`{"id", "ts", "label": "right"|"wrong", "note"}`, appended by `claude-guard review ID LABEL
[NOTE…]`. `reviews(root)` folds the file to the **latest** mark per id, so re-marking corrects
a mark.

### `review(args, cfg, out)`

| Call | Behaviour |
|---|---|
| `review` | decisions in the last 14 days that are **not reviewed** and are a `pivot`, an `extension` or a failure: id, time, verdict (`failed`), goal, prompt (≤110), reason or error |
| `review --days N` | window of N days |
| `review --all` | every decision in the window, reviewed or not, with the mark in brackets |
| `review ID right\|wrong [NOTE…]` | ID may be a prefix; exactly one decision must match (`N decisions match` otherwise, exit 1); appends the mark; prints `recorded: <id> is <label>` |
| a label other than `right`/`wrong` | usage, exit 1 |

Continuations are left out of the default list because they are the bulk and rarely wrong.
`--all` includes them.

## 11. Report — `report(args, cfg, out)`

- Arguments: `--days N` (default 14), and an optional path (default: the work root).
- Walks the path for `.quality.jsonl` files and keeps records with `ts >= now - N days`.
  Unparsable lines are skipped.
- Output:
  1. header: window, record count, current mode;
  2. counts by `(event, type, decision)`;
  3. judge: successful calls, median and p90 of `judge_ms` (errors excluded), failure count;
  4. judge review: `judge reviewed: R of N, X right, Y wrong` for decisions in the window,
     then the latest 5 wrong ones (id, prompt, verdict, note);
  5. overrides (`force:`) count;
  6. the latest 8 of each of `pivot`, `depth`, `loop`: time, folder (relative to the root),
     the prompt or the reached identifiers or the tool (or "(end of answer)" for a stop), and
     the reason.

---

## 12. Failure behaviour (fail open)

| Failure | Effect | Logged |
|---|---|---|
| Config file missing or unreadable | defaults (mode `off`, so the guard is inactive) | no |
| Invalid mode value | `off` | no |
| Payload not JSON / not a dict | no answer, exit 0 | stderr |
| Any exception in a hook | no answer, exit 0 | stderr |
| `.scope.json` corrupt | treated as empty and rewritten | no |
| `.quality.jsonl` not writable | decision still returned | stderr |
| `claude` not on PATH, not logged in, gateway error, bad output | prompt allowed | `judge_error` |
| Judge timeout | prompt allowed | `judge_error`, `judge_ms` |
| Background judge can't start (shadow) | prompt allowed | `judge_error` |
| `CWS_GUARD_PROFILE` names a profile with no `~/.claude-<name>` | judge not called; prompt allowed | `judge_error`, journal `error` |
| `_audit/guard/` not writable | decision still applied and logged in the folder | stderr |
| Hook killed by Claude Code's timeout | non-blocking per spec | no |
| Judge process fires hooks | none: `disableAllHooks`, and `CWS_GUARD_JUDGE` silences the guard anyway | — |

---

## 13. Installation

### 13.1 `install.sh`

For each profile `~/.claude-<p>/settings.json` (in the "Claude Code profiles" step), the
hook merge adds any missing entry, matched by exact `command`, and keeps the user's own hooks:

| Event | Matcher | Command | Timeout (s) |
|---|---|---|---|
| `PostToolUse` | `Bash\|mcp__.*` | `~/.local/bin/claude-hook-notfound` | 10 |
| `PostToolUseFailure` | `Bash\|mcp__.*` | `~/.local/bin/claude-hook-notfound` | 10 |
| `UserPromptSubmit` | — | `~/.local/bin/claude-hook-vague` | 10 |
| `UserPromptSubmit` | — | `~/.local/bin/claude-guard prompt` | 30 |
| `PreToolUse` | `Read\|Glob\|Grep\|WebFetch\|WebSearch\|Bash\|mcp__.*` | `~/.local/bin/claude-guard tool` | 5 |
| `Stop` | — | `~/.local/bin/claude-guard stop` | 10 |

It also:

- symlinks `bin/claude-guard` into `~/.local/bin`;
- copies `config/guard-rules.example.md` to `_config/guard-rules.md` if absent;
- writes the file atomically (temp file + `os.replace`), keeping its permissions, and
  honours `--dry-run`.

The hooks are registered whatever the mode. With `CWS_GUARD_MODE=off` (the default) each
call reads the config and exits.

### 13.2 `uninstall.sh`

Removes the three `claude-guard <event>` commands (and the other prompt-quality hooks) from
each profile's settings, drops empty groups and events, and removes the symlink.

---

## 14. Shell changes (`shell/worksessions.zsh`)

### 14.1 `claude-new`

- New options: `-g` / `--goal TEXT`, `--done TEXT`.
- Interactive (stdin is a terminal) and `-g` not given: after the task type, it asks
  `Goal — what should this session deliver? [<name>]`, then `Done when (Enter to skip)`
  unless `--done` was given.
- A blank goal becomes the session name. Without a terminal it never asks.
- `.session.json` gains `"goal"` and `"done_when"`.

### 14.2 `claude-goal`

```
claude-goal                      → prints "goal: …" and "done when: …"
claude-goal TEXT… [--done TEXT]  → re-anchor
claude-goal --done TEXT          → change done-when only
```

It walks up from `$PWD` to the nearest `.session.json` inside `$CLAUDE_WORK_ROOT`, and fails
with `claude-goal: no .session.json here …` outside one. To re-anchor it:

1. appends `{"goal": old, "done_when": old, "until": <ts>}` to `goal_history`;
2. sets `goal` (unchanged when only `--done` is given) and `done_when`;
3. in `.scope.json`, removes `literal`, `targets` and `open` for **every** session in the
   folder, keeping `prompt_no` and `turn`, so the next prompt is judged as a first request;
4. appends a `goal` event to `.quality.jsonl`.

---

## 15. Related change: `claude-hook-notfound`

For `tool_name == "Bash"` with a dict `tool_response` that has a `stderr` key, only `stderr`
is scanned. `stdout` of a successful command is content (`git log`, `cat`, `sed` of source
code) and produced false alarms. MCP responses, `error` (failures) and `tool_output` are
scanned as before.

---

## 16. Concurrency and ordering

- **Shadow, first seconds of a request.** Tool calls can run before the background judge
  returns. The prompt's own names are already targets. If there are none and no earlier
  targets exist, nothing is flagged.
- **Judge vs tool hook.** Both take the `flock`. The judge holds it only while merging.
- **Two sessions in one folder.** They share the lock and have separate entries. Their
  `.quality.jsonl` lines interleave and are told apart by `session_id`.
- **Late verdicts.** These are applied only if `prompt_no` still matches (§6.4).
- **Synced work root (OneDrive, iCloud).** The files are small and rewritten whole. A sync conflict copy would be
  ignored, since only `.scope.json` is read.

---

## 17. Measured performance (2026-09-26, macOS, Haiku through a subscription profile)

| Operation | Measured |
|---|---|
| `claude-guard tool` round trip | 36 ms |
| Judge call, custom system prompt | 7.0–10.9 s |
| Judge cost | $0.0039–0.0045 per call |
| Judge cost with the default system prompt (not used) | $0.018 per call |

---

## 18. Tests

| File | Covers |
|---|---|
| `tests/test_guard.py` (30 tests) | extraction and matching; `trivial`; folder resolution and settings; config parsing and the ignore list; shadow background spawn and spawn failure; `force:` and widening; enforce pivot blocking without widening the scope; first-prompt rule; late verdicts; each judge failure mode; rules file; no-op outside request folders; out-of-scope logging, de-duplication and denial; safe roots; loops (denied from the 3rd call, logged once); repeated out-of-scope calls denied every time, logged once; stop blocking once, shadow stop summary; `main` silence rules and fail-open; corrupt state; report output; judge profile (inherited, configured, missing → fail open); journal content and id join; review listing, `--all`, `--days`, prefix marking, errors; report agreement; journal write failure |
| `tests/test_shell.py` | `claude-new` goal/done flags, interactive prompts and the non-interactive default; `claude-goal` show, re-anchor, scope reset, log line, done-only change and the error outside a folder; `install.sh` registers the guard hooks with their matchers and timeouts and seeds `guard-rules.md`; `uninstall.sh` removes them |
| `tests/test_quality.py` | `claude-hook-notfound` ignores Bash stdout and still catches stderr and MCP output |

The judge is replaced by a fake `subprocess.run` in the tests. The real call was verified end
to end in shadow mode against a throwaway work root. The suite has 330 tests, with coverage
at 99% (`claude-guard` 99%).

---

## 19. Tunables and constants

| Name | Where | Value | Effect |
|---|---|---|---|
| `CWS_GUARD_MODE` | config | `off` | mode |
| `CWS_GUARD_MODEL` | config | `haiku` | judge model |
| `CWS_GUARD_JUDGE_TIMEOUT` | config | `15` | seconds (enforce and background) |
| `CWS_GUARD_PROFILE` | config | — | profile the judge runs under |
| `CWS_GUARD_IGNORE_NAMES` | config | — | extra code-object first parts to ignore |
| `_config/guard-rules.md` | work root | example | the judge's criteria |
| `LOOP_AFTER` | code | 3 | identical calls per request that make a loop |
| investigation threshold | code (`on_stop`) | 2 reading calls | when proposals are expected |
| proposal window | code (`on_stop`) | last 800 chars | where proposals are looked for |
| prompt sent to the judge | code | 4,000 chars | truncation |
| logged prompt / literal / reason | code | 200 / 300 / 400 chars | log size |
| report window / rows | code | 14 days / 8 per type | defaults |

---

## 20. Known limitations

1. **Enforce latency.** Every non-trivial prompt waits for the judge (~10 s). A candidate
   optimisation is to skip the judge when all the prompt's names already match the targets
   and there is no widening.
2. **Targets accumulate** across a session's requests and are cleared only by `claude-goal`.
   A long session gradually allows more.
3. **Identifiers without names**, such as GUIDs and numeric ids passed to MCP tools, are not
   extracted, so those calls are never flagged.
4. **Keyword lists** (`CONFIRM`, `WIDEN`, `PROPOSALS`) are English and Portuguese, in code.
5. **The proposals check is lexical.** It confirms the closing structure, not that the
   proposals are good.
6. **`WebSearch`** is flagged whenever there are targets and the query doesn't contain one,
   which can over-flag documentation lookups.
7. **Sessions outside a request folder** are not guarded.
