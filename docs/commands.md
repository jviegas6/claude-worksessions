# Commands

## claude-new

```
claude-new [-p PROFILE] [-n|-a] [-c] [-t TICKET] [-T TYPE] [--prompt TEXT] [name]
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
  `claude-search` still finds it. `-a` / `--audit` keeps it in. With neither, `claude-new`
  asks *Count it in the weekly review and daily recap? [Y/n]* — Enter keeps it in. Run
  without a terminal it doesn't ask, and counts the session.
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
- `--prompt TEXT` starts Claude with `TEXT` as its first prompt — `--prompt /weekly-review`
  opens the new request straight into that skill. Not with `-c`.
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
prompt (Claude Code keeps both in the transcript), when it started, the files it wrote, and its request
folder with name, ticket, task type, profile and files. Written files are read once:
`~/.cache/claude-worksessions/written.json` remembers how far each transcript was read. A session belongs to the nearest folder with a
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
| arrows icon (top) | sort by **last activity** (a resumed session moves up), **started** (newest first; resuming moves nothing) or **name**; remembered. By day always lists days newest first |
| a session | open it in a tab (`claude-resume -p <profile> --resume <id>`), or go to its tab if open |
| **+** on a request | a new session in that request's folder, with its profile |
| pin on a session or request | **Pin** it: a **Pinned** group at the top lists it whatever the grouping and sort (also right-click → Pin / Unpin). Pins live in `<work root>/_config/pinned.json`, so they follow the work root to other machines |
| folder on a request | reveal it in the Explorer (right-click: in Finder, a new window, set task type) |
| **Files** under a request | the request folder's files as a tree — click to open (Markdown in the preview), right-click to reveal in Finder or copy the path |

**Search box.** Above the tree: typing filters it to the sessions whose title, prompts,
request name, ticket, task type, profile, folder or file names contain every word — and a
request's **Files** narrow to the files that match, and opens every
group so the matches show; `Esc` or the clear button in the title bar resets it. **Enter**
runs `claude-search` on the text, which also looks inside the conversations, and lists
the hits to pick from. Drag the divider to resize the box; VS Code remembers it.

**Commands.** In the Command Palette under *Work sessions* (and in the `…` menu of the
panel), the terminal commands and your skills:

| command | does |
|---|---|
| New request | `claude-new` in a tab |
| Recent sessions… | `claude-sessions` as a pick list; picking opens the session |
| Search sessions… / with Claude… | `claude-search` (`--ai`), hits in a pick list |
| Audit… | `claude-audit` for today, this or last week, this month, a day or a week; summary or detail |
| Set task type… | `claude-type`: on a session (right-click, the focused tab, or pick one) or on a request (its default) |
| Go to request… | `ws`: open a request in a new window, reveal it, or start a session in it |
| Run skill… | any skill in `~/.claude-*/skills`: a new request (`claude-new --prompt /<skill>`), so it gets its ticket, type and folder |
| Resume session by id… | `claude-resume --resume ID` in a tab |
| Focus the search box · Clear search | |

Sessions are named by Claude's auto-title, else their first prompt; hovering shows the
title, first and latest prompt, ticket, type, profile, age, and the files the session
wrote (from its Write / Edit tool calls). Open sessions have a
green terminal icon. Tabs are named `TICKET · title`; a tab opened with **+** takes its
session's name once its first prompt is in. The list refreshes itself as transcripts
and `.session.json` files change.

Tabs are editor terminals, not the Claude extension's chat tabs: those always run in
the window's first folder, so they can't hold sessions from different requests. Diffs
still open in VS Code, since Claude in VS Code's terminal connects to it (`/ide` if not).

Settings: `claudeWorksessions.sessionsCommand` (default `~/.local/bin/claude-sessions`),
`claudeWorksessions.showEmptySessions` (sessions closed without a prompt; off).

## claude-delete

```
claude-delete ID              # say what goes, ask, then move it to the bin
claude-delete ID --yes        # without asking
claude-delete ID --check      # only say whether it may go and what that would mean
claude-delete ID --json       # the same, as JSON
claude-delete --list          # what is in the bin (--json too)
claude-delete --restore ID    # put a deleted session back where it was
claude-delete --purge ID      # delete it for good (asks; --yes)
claude-delete --empty         # delete everything in the bin for good (asks; --yes)
```

For clearing out test sessions and other noise. `ID` is a session id or its start.
A session may go only when it has **no value**:

- **no artifacts** — none of the files it wrote still exist, and if it is its request's
  only session, the request folder has no files either; or
- it is **kept out of the review** — started with `claude-new -n` (`"audit": false`), or
  listed in `_audit/no-audit.txt`.

Never when the weekly review booked it (it is in `_audit/review/ledger.json`), when a
Claude process has it open (Claude Code's `~/.claude-*/sessions/<pid>.json` records, or
`claude --resume ID` on a command line), or when it was written in the last two minutes.
Before anything moves it says what deleting means: the conversation can't be resumed or
found, whether its time leaves your audit, which files it produced (those stay), and
whether its request folder goes too.

**The bin** is `~/.local/share/claude-worksessions/trash` (`$XDG_DATA_HOME` if set;
`CWS_TRASH_DIR` overrides) — local, like the transcripts, never the synced work root. Each
deleted session gets a folder there with its pieces and a `manifest.json` of where each came
from: its transcript and any copies left by a folder move, its subagent logs, file history
and session environment, and its request folder when it was the folder's only session and
nothing but `.session.json` is in it. Files it wrote are never touched. A pin on it is
removed. `--restore` puts every piece back (and refuses, moving nothing, if something now
sits where one of them was); `--purge` / `--empty` delete for good.

In VS Code: right-click a session → **Delete session…**, offered only on sessions that
qualify; it shows the same summary and asks. Deleted sessions are listed under **Deleted**
at the bottom of the panel: right-click → **Restore** (or the inline icon) or **Delete for
good…**; right-click **Deleted** → **Empty the bin…**.

## claude-md-email

```
claude-md-email FILE.md             # copy it, formatted, to the clipboard
claude-md-email FILE.md --open      # open it as a web page instead
claude-md-email FILE.md --html OUT  # write the HTML ('-' for stdout)
```

Renders Markdown with pandoc and styles it with `yazi/md-email.css` — black on white,
Calibri 11pt, bordered tables with shaded headers — so it pastes into Outlook looking
like an email, whatever theme your editor uses. The styles are written onto every
element, because Outlook drops a `<style>` block on paste. The clipboard also gets the
Markdown as plain text.

In VS Code it is **Copy for email**: the envelope button on a Markdown file or its
preview, the editor's right-click menu, the Explorer's, and the sidebar's **Files**.
Unsaved changes are saved first.

Clipboard: macOS natively; WSL through Windows PowerShell (`Set-Clipboard -AsHtml`);
Linux with `wl-copy` (Wayland) or `xclip`.

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
