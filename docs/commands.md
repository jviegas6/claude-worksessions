# Commands

## claude-new

```
claude-new [-p PROFILE] [-n] [-c] [-t TICKET] [-T TYPE] [name]
claude-new -l
claude-new -L
```

Creates `<work root>/YYYY/MM/DD/HH-mm-ss_slug/`, writes `.session.json` (name, slug,
profile, ticket, audit flag, start/end, host, path), cd's in and starts Claude with
that profile. `ended_at` is filled in when Claude exits.

- **Ticket is mandatory**: `PREFIX-123` or `Other`. A ticket-shaped first word is taken
  as the ticket: `claude-new PROJ-123 cost pipeline`.
- `-p name` / `--profile name` picks the profile — any name in `CWS_PROFILES`, so a
  new profile needs no code change. Left out, you get a menu. An unknown name is an error.
- `-n` / `--no-audit` keeps the session out of `claude-audit` and the weekly review.
  `claude-search` still finds it.
- `-T type` / `--type` sets the **task type** — what kind of work *starts* this session
  (permissions, job errors, new features, security, ...). Left out, `claude-new` guesses
  from the name and offers the types you have used before: Enter takes the guess, a
  number picks from the list, anything else is a new type, `-` means none. When nothing
  in the name matches there is no default — it asks you to pick.
  The type is the **trigger**, not the detours: a job error that needs investigation, a
  permission change and a doc update is `job errors`.
- `-c` / `--code` opens the new folder in a new VS Code window instead of starting
  Claude in the terminal. Start Claude from the extension there; it runs with the
  session's profile through [`claude-vscode`](#claude-vscode). `ended_at` stays empty,
  since nothing waits for VS Code to close.
- `-l` lists the 15 most recent sessions with profile, ticket and type.
- `-L` / `--profiles` lists the configured profiles: which is the default and which is
  shared, the description, the gateway URL if any, and a warning if `~/.claude-<name>`
  is missing.

## claude-resume

```
claude-resume [-p PROFILE] [--] [claude args...]
```

Runs Claude Code with a profile (default `CWS_DEFAULT_PROFILE`). Everything except `-p`
goes to `claude` unchanged, so `claude-resume -p work --resume ID` or `-c` work as usual.
With no claude arguments it adds `--resume`, which opens the session picker. `--` ends
its own options, for claude's `-p` (print mode): `claude-resume -p work -- -p "question"`.
This replaces the per-profile `claude-<name>` aliases.

## claude-vscode

Not run by hand: `install.sh` sets it as the Claude extension's
`claudeCode.claudeProcessWrapper` in VS Code's user settings (on WSL, the remote machine
settings in `~/.vscode-server/data/Machine/`). The extension then starts Claude as
`claude-vscode <claude> [args]` in the workspace folder. If that folder, or one above it,
has a `.session.json`, Claude gets that session's profile (`CLAUDE_CONFIG_DIR=~/.claude-<profile>`),
gateway included; anywhere else it runs with whatever the extension's own settings say.

The extension's `claudeCode.environmentVariables` can't do this: it is a machine-wide
setting, so every window would get the same profile.

Open a request folder as the VS Code workspace (`claude-new -c`, `ws -c`, or
*File → Open Folder*) so the extension's sessions run there. A window opened on the
work root gets the default profile and no `.session.json`, like a bare `claude` there.

## claude-type

```
claude-type                       show the current type, and whether it is this session's or the folder's
claude-type security              set it for THIS session (run anywhere inside the session folder)
claude-type --folder security     set the request folder's default instead
claude-type --backfill [--apply]  guess a folder default for older sessions that have none
```

Types live in `.session.json`: `task_type` is the folder's default, and `session_types`
maps a session id to its own type. **A session's own type wins**, so one request folder
can hold sessions that went different ways — resume a folder for something else and only
that session is relabelled. The session is identified by its transcript in
`~/.claude-<profile>/projects/`; outside a running session there is nothing to identify,
so `claude-type` sets the folder default and says so.

One caveat: a resumed session keeps one id across days, so its type covers the whole
session, not just today's part of it.

The type feeds `claude-audit --by-type`, the daily recap and the weekly review. Claude
changes it itself when a session's subject clearly shifts, and says so. `--backfill`
guesses from the session name — it prints what it would set, and only writes with
`--apply`.

## claude-audit

```
claude-audit [--day [DATE] | --week [DATE] | --month [YYYY-MM] | --from DATE --to DATE]
             [--detail | --reconcile | --sessions | --by-type] [--copy] [--csv [FILE]]
claude-audit --week DATE --propose        # weekly review: what needs deciding
claude-audit --apply decisions.json       # weekly review: record decisions in the ledger
claude-audit --schema                     # the activity-file format the skills write
```

`--by-type` groups the period's hours by task type (sessions without one show as
`(no type)`). The weekly summary table and CSV carry a **Task Type** column; `--copy`
leaves it out so the clipboard still matches the tracker's own columns.

| flag | Task Type in table & CSV | in `--copy` |
|---|---|---|
| (default) | yes | no |
| `--with-type` | yes | yes — for a tracker that has the column |
| `--no-type` | no | no |

Reads every transcript under `~/.claude-<profile>/projects`, measures time actually
worked (stalls capped), and merges the meetings, mail and chats the skills saved in
`_audit/activity/`. The summary is one row per task and ticket per week; `--detail` is
every activity behind it. `claude-audit --help` has the full list.

## claude-search

```
claude-search QUERY... [--from DATE] [--to DATE] [--ai] [--no-pick] [--csv FILE]
```

Ranks past sessions by ticket or topic across titles, your prompts, Claude's replies,
commands run and linked meetings/mail. Prints the resume command for each and offers
to resume one (`--no-pick` just lists). `--ai` asks Claude to judge relevance.

## claude-sessions

```
claude-sessions [N]      # the N most recent sessions (default 30)
claude-sessions -a       # all of them
claude-sessions --json   # as JSON, for the VS Code sidebar
```

One line per session, newest first: last activity, session id, the folder it ran in
and the first prompt. Folders moved since are shown where they are now
(`_audit/moved-folders.json`), and a session is listed once even when a move left a
copy of its transcript under the old folder.

`--json` adds what the VS Code sidebar shows: each session's auto-title and latest
prompt (Claude Code keeps both in the transcript), and its request folder with name,
ticket, task type and profile. A session belongs to the nearest folder with a
`.session.json` above where it ran, else the `YYYY/MM/DD/slug` folder it is in, else
the one it was assigned to in `_audit/session-folders.json`.

## VS Code sidebar

`install.sh` installs a **Work sessions** extension into VS Code when the `code` command
is on your PATH (in VS Code: *Shell Command: Install 'code' command in PATH*), at the
same version as the rest; `--update` updates it. Reload open windows after installing.

It adds a sidebar (the history icon) listing your requests and their Claude sessions.
Open a window on the work root and use it instead of `claude-new -c`'s one window per
request: every session opens as a **terminal tab in the editor area**, running in its
own folder with its own profile, so requests on different tickets and profiles sit side
by side.

| in the sidebar | does |
|---|---|
| **+** (top) | new request: a tab running `claude-new`, with its usual prompts |
| list icon (top) | group by **day**, by **ticket**, or a flat list of **recent** sessions; remembered |
| a session | open it in a tab (`claude-resume -p <profile> --resume <id>`), or go to its tab if open |
| **+** on a request | a new session in that request's folder, with its profile |
| folder on a request | reveal it in the Explorer (right-click: in Finder) |

Sessions are named by Claude's auto-title, else their first prompt; hovering shows the
title, first and latest prompt, ticket, type, profile and age. Open sessions have a
green terminal icon. Tabs are named `TICKET · title`; a tab opened with **+** takes its
session's name once its first prompt is in. The list refreshes itself as transcripts
and `.session.json` files change.

Tabs are editor terminals, not the Claude extension's chat tabs: those always run in
the window's first folder, so they can't hold sessions from different requests. Diffs
still open in VS Code, since Claude in VS Code's terminal connects to it (`/ide` if not).

Settings: `claudeWorksessions.sessionsCommand` (default `~/.local/bin/claude-sessions`),
`claudeWorksessions.showEmptySessions` (sessions closed without a prompt; off).

## ws, y

| command | does |
|---|---|
| `ws` | fuzzy-pick a request folder (newest first), cd into it |
| `ws -y` | … and browse it in yazi |
| `ws -o` | … and open it in Finder (Explorer on WSL, the file manager on Linux) |
| `ws -c` | … and open it in VS Code |
| `y` | yazi; quitting leaves the shell where you were in yazi |

## yazi, for Markdown

| key on a `.md` | does |
|---|---|
| (select it) | rendered preview on the right (glow, no `#` markers) |
| `Enter` | open as HTML in the browser — select all, copy, paste into Outlook with real tables |
| `O` → Glow | full-screen rendered view, `q` returns |
| `O` → Glow (light) | same, light theme, for iTerm2 *Copy with Styles* |
| `O` → open | the system's default app |

HTML styling is `~/.config/yazi/md-email.css`; the converter is
`~/.config/yazi/md2html.sh FILE.md`, usable on its own.

In iTerm2, set *Settings → Profiles → Advanced → Semantic History* to open with your
editor, so ⌘-click on a path Claude prints opens the file.
