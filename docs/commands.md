# Commands

## claude-new

```
claude-new [-w|-p|-P PROFILE] [-n] [-t TICKET] [name]
claude-new -l
```

Creates `<work root>/YYYY/MM/DD/HH-mm-ss_slug/`, writes `.session.json` (name, slug,
profile, ticket, audit flag, start/end, host, path), cd's in and starts Claude with
that profile. `ended_at` is filled in when Claude exits.

- **Ticket is mandatory**: `PREFIX-123` or `Other`. A ticket-shaped first word is taken
  as the ticket: `claude-new PROJ-123 cost pipeline`.
- `-w` / `-p` pick the `work` / `personal` profile, `-P name` any profile; otherwise
  you get a menu.
- `-n` / `--no-audit` keeps the session out of `claude-audit` and the weekly review.
  `claude-search` still finds it.
- `-T type` / `--type` sets the **task type** — what kind of work this is
  (permissions, job errors, new features, security, ...). Left out, `claude-new` guesses
  one from the name and offers the types you have used before; Enter takes the guess, a
  number picks from the list, anything else is a new type, `-` means none.
- `-l` lists the 15 most recent sessions with profile, ticket and type.

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

## ws, y

| command | does |
|---|---|
| `ws` | fuzzy-pick a request folder (newest first), cd into it |
| `ws -y` | … and browse it in yazi |
| `ws -o` | … and open it in Finder |
| `ws -c` | … and open it in VS Code |
| `y` | yazi; quitting leaves the shell where you were in yazi |

## yazi, for Markdown

| key on a `.md` | does |
|---|---|
| (select it) | rendered preview on the right (glow, no `#` markers) |
| `Enter` | open as HTML in the browser — select all, copy, paste into Outlook with real tables |
| `O` → Glow | full-screen rendered view, `q` returns |
| `O` → Glow (light) | same, light theme, for iTerm2 *Copy with Styles* |
| `O` → open | the macOS default app |

HTML styling is `~/.config/yazi/md-email.css`; the converter is
`~/.config/yazi/md2html.sh FILE.md`, usable on its own.

In iTerm2, set *Settings → Profiles → Advanced → Semantic History* to open with your
editor, so ⌘-click on a path Claude prints opens the file.
