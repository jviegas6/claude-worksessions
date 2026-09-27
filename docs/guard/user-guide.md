# claude-guard — User guide

claude-guard keeps a Claude session on the job you gave it:

- **It does what you asked, literally**, and ends by *proposing* what could be looked at next
  instead of going off to look at it.
- **It notices when you change objective** mid-session, so a new piece of work can start in its
  own session with a clean context.
- **It notices loops**: the same command run over and over.

It works in the background through Claude Code hooks. You don't call it during a session.
You set a goal when you start, and optionally review what it saw.

Technical details: [High-Level Design](hld.md) · [Low-Level Design](lld.md). For claude-worksessions as a whole: [user guide](../user-guide.md).

---

## 1. Turning it on

The guard is installed with claude-worksessions (`./install.sh`) and starts **off**. Set the
mode in `<work root>/_config/config.env`:

```sh
CWS_GUARD_MODE="shadow"     # off | shadow | enforce
```

| Mode | What you notice |
|---|---|
| `off` | nothing; the guard does nothing |
| `shadow` | **nothing**. It decides everything and writes it to a log, but never blocks or slows you down |
| `warn` | a one-line **notice** from `claude-guard` where enforce would act: a new objective, a read outside the request, a loop, missing next steps. Never blocks, never slows prompts; a verdict on your prompt appears with Claude's answer (the end of a short answer can take a few seconds more while the judge finishes) |
| `enforce` | it blocks new objectives, stops Claude reading things outside the request, and asks Claude for next-step proposals. Prompts take a few seconds longer while the judge decides |

The mode is read on every hook call, so changing it takes effect on the next prompt with no
restart. Start with **shadow** for a week or two, review it (§6), then switch to **enforce**.

> The guard only watches sessions that run inside a request folder (`YYYY/MM/DD/HH-mm-ss_slug/`),
> which is where `claude-new` starts them.

---

## 2. Starting a session with a goal

`claude-new` now asks two more questions:

```
Goal — what should this session deliver? [vnet peering issue]: find why the peering from hub to spoke fails
Done when (Enter to skip): root cause identified and the fix listed
```

- **Goal**: what this session is for. Press Enter to use the session name.
- **Done when**: how you'll know it's finished. Optional, but it helps the judge tell a
  follow-up from a new objective.

Or give them on the command line:

```sh
claude-new -t PROJ-123 -g "list the sources of the sales model" --done "a table of sources" sales model sources
```

The more concrete the goal, the better the guard's judgements.

---

## 3. What happens during a session (enforce)

### 3.1 You change objective

You ask something that isn't needed for the session's goal, even if it's on a related topic:

> Goal: *fix the access policy on the orders table*
> You: *what access-control mechanisms does the platform offer overall?*

The prompt is blocked, and you see:

```
claude-guard: this looks like a new objective, not part of this session's goal (<why>).
Session goal: fix the access policy on the orders table
Start it in its own session (claude-new), re-anchor this one with claude-goal "..." if the goal
really changed, or resend it starting with force: to go ahead here.
```

You have three options:

| You want to… | Do this |
|---|---|
| treat it as separate work (usually right) | open a new session: `claude-new -t PROJ-123 "access-control survey"` |
| change this session's objective on purpose | in a terminal in the session folder: `claude-goal "survey the access-control mechanisms"`, then resend the prompt |
| just ask it here, this once | resend it starting with `force:` — `force: what access-control mechanisms…` |

**Widening adds up.** Applying the goal to one more thing in the same system is fine ("also the
customers table", "and the UAT environment"). But after two such widenings, the next one counts
as a new objective (`CWS_GUARD_MAX_EXTENSIONS`). A different product or platform is a new
objective straight away: goal "understand the Databricks API", then "what about Snowflake?".

These don't count as a new objective:

- **Follow-ups and fixes**: "it fails with permission denied, why?", "now test it".
- **Extensions of the same goal**: "apply the same policy to the customers table too".
- **Confirmations and commands**: "yes", "go ahead", "/review".

The **first** prompt of a session is never blocked, because it defines the scope.

### 3.2 Claude reaches outside the request

You ask *"list the sources of the orders model"*, and Claude tries to open one of those
sources to look inside. That read is denied, and Claude is told to list it as a possible next
step instead. You see the denial in the transcript, and the answer ends with suggestions like
"Next: open `db.staging.orders_raw` to check its freshness".

Always allowed:
- files in the session folder, the scratchpad and temp folders, and Claude's own config;
- anything named in your prompts (paths, URLs, `db.schema.table` names, snake_case names) or
  identified by the judge as a target;
- **a git repo Claude edits** in this session: from its first edit there, the whole repo is in scope;
- **a git repo you name** in the goal or a prompt, by its folder name ("fix the installer in
  claude-worksessions");
- **folders you declare**: `claude-new --path ~/Repos/sales-etl`, or later
  `claude-goal --path ~/Repos/sales-etl`.

Everything else outside the session folder is out of scope, including `../` paths.

### 3.3 You *want* it to go further

Say so in the prompt, and the target check is lifted until your next request:

- English: *go deeper*, *dig into*, *deep dive*, *explore*, *in depth*, *expand on*
- Portuguese: *aprofunda*, *mais a fundo*, *explora*

Example: *"go deeper into the sources and check their refresh schedules"*.

### 3.4 Claude repeats itself

The third identical call in the same request (same tool, same input) is denied, and Claude is
told to change approach or ask you.

### 3.5 Claude finishes an investigation

If Claude read or searched for your request and its answer doesn't end with what could be
examined next, it's asked, once, to add a short list of proposals. It doesn't carry them out.

---

## 4. Commands

| Command | What it does |
|---|---|
| `claude-new … -g GOAL --done TEXT` | start a session with a goal (asked if omitted) |
| `claude-goal` | show the current session folder's goal and done-when |
| `claude-goal "new goal" [--done "…"]` | change the goal on purpose; the old one is kept in the history and the guard starts a fresh scope |
| `claude-goal --done "…"` | change only done-when |
| `claude-new … --path DIR` / `claude-goal --path DIR` | a folder or repo outside the request that is part of the work (repeatable) |
| `claude-guard report` | what the guard saw in the last 14 days, across all sessions |
| `claude-guard report --days 7` | a different window |
| `claude-guard report <folder>` | one request folder, or one day (`<work root>/2026/09/26`) |
| `claude-guard review` | the judge's decisions you haven't reviewed yet (new objectives, extensions, failures) |
| `claude-guard review --all` | every decision, with your marks |
| `claude-guard review ID right\|wrong [note]` | mark a decision as right or wrong, with an optional note |

Inside a prompt:

| Prefix / words | Effect |
|---|---|
| `force:` at the start | this prompt skips the guard (recorded as an override) |
| *go deeper*, *aprofunda*, … | lifts the target check until the next request |

> Use `force:`, not `!force`. In Claude Code a prompt starting with `!` runs as a shell command.

---

## 5. Where things are recorded

In each request folder:

| File | Holds |
|---|---|
| `.session.json` | `goal`, `done_when`, and `goal_history` after a `claude-goal` |
| `.quality.jsonl` | one line per guard decision: time, what happened, the decision, and why |
| `.scope.json` | the guard's working state: the current request's scope and targets |

And for all sessions together, in `<work root>/_audit/guard/`:

| File | Holds |
|---|---|
| `judge.jsonl` | every decision of the judge, complete: the goal, done-when and scope it was shown, the prompt, its verdict and reason, the model, profile and time |
| `reviews.jsonl` | your marks on those decisions (`claude-guard review`) |

A line in `.quality.jsonl` looks like this:

```json
{"ts": "2026-09-26T21:57:12Z", "event": "prompt", "decision": "block", "type": "pivot",
 "initiated_by": "user", "verdict": "pivot", "prompt": "what access-control mechanisms…",
 "reason": "a platform-wide survey is a different deliverable from fixing one policy", "judge_ms": 7056}
```

- `type`: `ok`, `pivot` (new objective), `depth` (outside the request), `loop`.
- `decision`: what enforce does, or **would** do in shadow.
- `initiated_by`: `user` for prompts and goal changes, `agent` for Claude's tool calls and answers.

---

## 6. Reviewing shadow mode

### 6.1 Mark the judge's decisions

Every few days, go through what the judge decided:

```sh
claude-guard review
```

```
claude-guard review: 2 decision(s) to review

  3fa9c1d2e0  2026-09-26T21:57  pivot
    goal:   fix the access policy on the orders table
    prompt: what access-control mechanisms does the platform offer overall?
    why:    a platform-wide survey is a different deliverable from fixing one policy

  a81c07b5f2  2026-09-27T09:12  pivot
    goal:   find why the nightly load fails
    prompt: and the permissions on the target folder?
    why:    permissions are a separate topic
```

Mark each one. The id can be shortened, and a note says why:

```sh
claude-guard review 3fa9 right
claude-guard review a81c wrong "permissions were the cause of the failure: a follow-up"
```

The wrong ones, with your notes, are exactly what to fix in `guard-rules.md` (§7.1). Changed
your mind? Mark it again; the latest mark counts.

### 6.2 The overall picture

After a week or two, run:

```sh
claude-guard report --days 14
```

```
claude-guard: last 14 days, 212 records, mode now shadow

  event    type    decision     n
  prompt   ok      allow      121
  prompt   pivot   block        9
  stop     depth   block       31
  stop     ok      allow       20
  tool     depth   deny        27
  tool     loop    deny         4

  judge: 130 calls, median 8.4s, p90 11.2s, 0 failed
  judge reviewed: 12 of 130, 10 right, 2 wrong
    wrong a81c07b5f2: and the permissions on the target folder? -> pivot (permissions were the cause…)

  Pivots (latest 8):
    2026-09-26T21:57  2026/09/26/10-00-00_access-policy
      what access-control mechanisms does the platform offer overall?
      -> a platform-wide survey is a different deliverable from fixing one policy
  …
```

Check these before switching to enforce:

| Look at | Healthy | If not |
|---|---|---|
| **judge reviewed**: how many marked wrong? | few | adjust `_config/guard-rules.md` from the wrong ones and their notes (§7) |
| **Pivots**: were they really new objectives? | mostly yes | adjust `_config/guard-rules.md` (§7) |
| **Out of scope**: were those reads really unnecessary? | mostly yes | see §7: ignore names, or accept that "go deeper" will be needed more |
| **Loops** | few | — |
| **judge failed** | 0 | see §8 |
| **judge median** | a few seconds | in enforce every non-trivial prompt waits this long |

---

## 7. Tuning

### 7.1 What counts as a new objective

`<work root>/_config/guard-rules.md` holds the judge's instructions, in plain language. Edit it
to fit how you work. For example, to be stricter about extensions or to add your own examples:

```markdown
- pivot: ... Example: goal "fix the nightly load job", prompt "redesign the scheduling of all
  jobs" is a pivot.
```

Changes apply from the next prompt.

### 7.2 Names that are code, not data

The guard reads names like `a.b.c` in commands as data objects. If your tools' commands contain
SDK objects that look like that (for example `client.jobs.list`), list their first parts:

```sh
CWS_GUARD_IGNORE_NAMES="client sdk"
```

### 7.3 Judge model, profile and patience

```sh
CWS_GUARD_MODEL="haiku"          # any model alias or name your profile can use
CWS_GUARD_PROFILE=""             # the profile the judge runs under (e.g. "personal"); empty = the session's own
CWS_GUARD_JUDGE_TIMEOUT="25"     # seconds; if the judge is slower, the prompt goes through (keep under 30)
```

---

## 8. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `claude-guard report` shows no records | mode is `off`; or the sessions didn't run inside a request folder; or no hooks (run `./install.sh`, then check `/hooks` in Claude Code) |
| `judge failed … Not logged in` | the judge's profile (the session's, or `CWS_GUARD_PROFILE`) isn't signed in. Run `claude` once with that profile, or set `CWS_GUARD_PROFILE` to one that is |
| `judge failed … judge profile dir … not found` | `CWS_GUARD_PROFILE` names a profile that doesn't exist; use a name from `claude-new -L` |
| `judge failed …` on the gateway profile | the gateway may not offer the configured model. Set `CWS_GUARD_MODEL` to one it has, or `CWS_GUARD_PROFILE` to another profile |
| `judge failed … timeout` | raise `CWS_GUARD_JUDGE_TIMEOUT` (below 30), or use a faster model |
| A read you needed was denied | name the repo or folder in the prompt, add it with `claude-goal --path`, or say "go deeper"; if it keeps happening, tune §7 |
| A follow-up was blocked as a new objective | resend with `force:`; add the case to `guard-rules.md` |
| Prompts feel slow in enforce | expected (judge time). Go back to `shadow` if it's too much |
| You want it gone for a while | `CWS_GUARD_MODE="off"`, effective on the next prompt |
| Remove it completely | `./uninstall.sh` removes the hooks and the command; your logs stay in the request folders |

Whatever goes wrong inside the guard, it lets your prompt or Claude's action through. It
can't break a session.
