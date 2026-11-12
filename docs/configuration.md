# Configuration

## Where the config is read from

1. `$CWS_CONFIG`, if set
2. `~/.config/claude-worksessions/config.env` — `install.sh` makes this a symlink to
   `<work root>/_config/config.env`

The zsh functions, `claude-audit`, `claude-search` and `install.sh` all read the same
file. Environment variables named `CWS_*` override it.

Format: `KEY="value"` lines, `#` comments, `$HOME` expanded. Nothing else is
interpreted — it is not executed as shell.

You don't have to write it by hand: the first `install.sh` asks for everything, and
`install.sh --reconfigure` asks again. Editing the file directly works
just as well — re-run `install.sh` afterwards so `CLAUDE.md` catches up.

## config.env

| key | default | used for |
|---|---|---|
| `CWS_WORK_ROOT` | `$HOME/work_sessions` | where request folders, `_audit/`, `_config/`, `_daily/` live |
| `CWS_ORG` | — | skills' wording; also ignored as a matching word in the audit |
| `CWS_USER_ROLE` | — | skills' wording ("a data/platform engineer at …") |
| `CWS_TIMEZONE` | `UTC` | IANA zone the recap normalises to |
| `CWS_TIMEZONE_WINDOWS` | `UTC` | the same zone as Outlook names it (e.g. `GMT Standard Time`) |
| `CWS_USER_NAME` | — | the weekly report's subject, `Weekly Report - <name>` |
| `CWS_REPORT_TO` | — | who the weekly report goes to, shown with the draft |
| `CWS_REPORT_DAY` | `Wed` | `claude-audit --report` covers the seven days before this weekday (Wed: Wednesday to Tuesday) |
| `CWS_REPORT_DUE` | — | the deadline shown with the draft (e.g. `18:00 CET`) |
| `CWS_ARCH_LOOKBACK_WEEKS` | `4` | `claude-audit --friday`: how far back a tracker phase counts as evidence for an active project |
| `CWS_ADR_REGISTER` | `_config/adr-register.md` | the Markdown table of ADRs (with a Status column) whose undecided rows are "decisions pending" |
| `CWS_TICKET_EXAMPLE` | `PROJ-123` | prompts and help text; any `PREFIX-123` or `Other` is accepted |
| `CWS_JIRA_CLOUD_ID` | — | the weekly review's Jira query (Atlassian MCP `getAccessibleAtlassianResources` gives it) |
| `CWS_CLAUDE_HOMES` | `~/.claude` | the Claude config dirs whose transcripts `claude-audit`, `claude-search`, `claude-sessions` and the sidebar read, space-separated; see [below](#claude-config-dirs) |
| `CWS_TASK_TYPES` | permissions, job errors, … | seed list of task types; the ones you have used are suggested first |
| `CWS_GUARD_MODE` | `off` | [`claude-guard`](commands.md#claude-guard): `off`, `shadow` (log only), `warn` (log and show a notice) or `enforce` (block) |
| `CWS_GUARD_MAX_EXTENSIONS` | `2` | how many times a session's goal can be widened before the next widening counts as a new objective |
| `CWS_GUARD_MODEL` | `haiku` | the model of the guard's judge |
| `CWS_GUARD_CONFIG_DIR` | — (the session's own) | the Claude config dir the guard's judge runs with — its login or gateway, and its cost |
| `CWS_GUARD_JUDGE_TIMEOUT` | `25` | seconds to wait for the judge in `enforce` before letting the prompt through |
| `CWS_GUARD_IGNORE_NAMES` | — | first parts of dotted names that are code, not data, in your commands (SDK objects), space-separated |
| `CWS_OPEN_CMD` | T3 Code | how `claude-new` opens a request: one command; see [below](#how-a-request-opens) |
| `CWS_AFTER_NEW_CMD` | `claude-area …` | what `claude-new` runs once the folder exists, before opening it |
| `CWS_T3_BIN` | `t3` on PATH, else `~/.t3/bin/t3` | T3 Code's command, for `claude-t3-sync` |
| `CWS_T3_PROVIDER`, `CWS_T3_MODEL` | the thread you used last in T3 | the provider instance id (T3's `providerInstances`, e.g. `claudeAgent`) and model of a thread `claude-t3-sync` starts in a project with no default model; T3 refuses one without them. Used only when both are set |
| `CWS_PROJECTS` | empty | big projects, each with its own heading in T3; see [`claude-area`](commands.md#claude-area) |
| `CWS_TYPES` | empty (off) | the types of request, e.g. `data access investigation`; the last is the fallback |
| `CWS_AREAS_DIR` | `~/.local/share/claude-worksessions/areas` | where the areas' git data lives; keep it outside the synced work root |
| `CWS_AREA_MODEL` | `haiku` | the model `claude-area --pick` asks |
| `CWS_AREA_TIMEOUT` | `20` | seconds to wait for it; after that the request stays ungrouped |
| `CWS_T3_IDLE_DAYS` | `14` | `claude-t3-sync` removes a request's T3 project after this many idle days, if it has no threads and isn't waiting on anyone |
| `CWS_INSTALL_YAZI` | `1` | install yazi, glow, pandoc and the Markdown extras |

Changing a value: edit the file, open a new terminal. Re-run `install.sh` when you
changed the work root or the Claude config dirs — the work root's `CLAUDE.md` is rendered from them. Org,
role, time zone, ticket example and Jira id are read by your skills at run time, so a new
session is enough.

## How a request opens

`claude-new` makes the folder and its `.session.json`, then runs two command templates:

| key | runs | default |
|---|---|---|
| `CWS_AFTER_NEW_CMD` | once the folder exists (T3's sidebar grouping, before T3 first sees it) | `claude-area --dir {dir} --pick {project} --type {type}` |
| `CWS_OPEN_CMD` | to open it | `claude-t3-sync --open {dir} --prompt {prompt}` |

`{dir}`, `{title}` (the request name), `{prompt}` (`--prompt`), `{project}` (`-A`) and `{type}`
(`-F`) are replaced by their values, shell-quoted, so each stays one argument whatever it holds.
An empty `CWS_OPEN_CMD` makes `claude-new` print the folder's path; an empty
`CWS_AFTER_NEW_CMD` runs nothing. Moving to another app is a line, not code:

```sh
CWS_OPEN_CMD="code {dir}"                  # VS Code
CWS_OPEN_CMD="open -a Terminal {dir}"      # a Terminal window (macOS)
CWS_AFTER_NEW_CMD=""                       # no T3, so no sidebar grouping
```

A config from before 3.1 has neither line: `CWS_OPEN="t3"` then means the T3 default, and
`claude-area`, when installed, runs as before.

## Claude config dirs

Which Claude login a session uses — a subscription, a company gateway — is the app's choice:
T3 Code's providers (Settings > Providers, one config dir each), or the IDE. worksessions only
needs to know where their transcripts are: `CWS_CLAUDE_HOMES`, e.g.
`"~/.claude-personal ~/.claude-work"`. A projects dir that two of them share through a link is
read once, and a session id found in an earlier dir is not counted again. Without the setting:
`~/.claude-<name>` for each name in an older `CWS_PROFILES`, else `~/.claude`.

`install.sh` creates nothing between them and leaves links made by older releases alone.

## Transcript retention

Claude Code deletes transcripts it hasn't written to for `cleanupPeriodDays` days —
**30 by default**. Those transcripts are what `claude-audit`, the weekly review, the
daily recap, `claude-search` and the VS Code sidebar read, so `install.sh` sets
`"cleanupPeriodDays": 3650` (about ten years) in each `CWS_CLAUDE_HOMES` dir's `settings.json` where
it isn't set. A value you set yourself is kept; if it is shorter, `install.sh` warns
that the audit will lose older sessions.

## context.md — standing context

Copied into the work root's `CLAUDE.md` by `install.sh`, so every session in the work
root knows it without being told. It is inlined rather than imported: Claude Code does
not expand an `@import` in a parent `CLAUDE.md` for a session running in a sub-folder,
and every session runs several folders down. Put the stable facts Claude would
otherwise rediscover: tenants, subscription ids, workspaces, storage accounts, repo
locations, naming quirks, hard-won rules of thumb, how you like answers. Ids and names
only — no secrets. After editing it, run `./install.sh` to copy it into `CLAUDE.md`.

## guard-rules.md — what the guard's judge counts as a pivot

The system prompt of [`claude-guard`](commands.md#claude-guard)'s judge: what makes a prompt
a *continuation*, an *extension* or a *pivot*, and how to state the literal scope and
targets. `install.sh` creates it from `config/guard-rules.example.md`; tune it from what
`claude-guard report` shows.

## review-rules.md — weekly-review house rules

Read by the `weekly-review` skill before it proposes anything; where it's more
specific than the skill, it wins. Typical content: the default task for unticketed
work, epics that catch a programme's work, tickets to ignore. Week-by-week decisions
don't go here — they are recorded in `_audit/review/ledger.json` by
`claude-audit --apply`.
