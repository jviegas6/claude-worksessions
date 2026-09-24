# Changelog

## [2.15.0] — 2026-09-24

- **`claude-retro`**: a retrospective on your prompts. Finds friction in the transcripts
  (missing resources, corrections, interruptions, rejected tool calls, reversals, clarifying
  questions — including ones asked in plain text), ties each to the prompt before it, and
  has Claude judge whether the prompt caused it and write a better one. Reports go to
  `_audit/quality/`, with a week-by-week trend; verdicts are cached.
- **A "does not exist" hook** (`claude-hook-notfound`), registered by `install.sh` in every
  profile: when a table, schema, group or Azure resource turns out not to exist, Claude is
  told to confirm with you before searching for alternatives. Existing hooks are kept;
  `uninstall.sh` removes it.

## [2.14.0] — 2026-09-23

- **VS Code: filter the sessions** by **day** (today, yesterday, last 7 days, this or last
  week, this month, or a date), **ticket** (one or more, or no ticket) and **artifacts**
  (with or without). A session counts on every day it was active. The funnel button opens
  a menu of the three; filters combine with the search box and each other, are
  remembered, and are listed in the panel's subtitle. The Deleted group hides while
  filtering.

## [2.13.0] — 2026-09-23

- **Deleted sessions can be seen and restored.** `claude-delete` now moves a session into
  its own bin — `~/.local/share/claude-worksessions/trash`, one folder per session with a
  manifest of where each piece came from — instead of the macOS Trash, which Finder can't
  *Put Back* from (it only restores what it trashed itself) and which macOS won't let
  other programs list. New `--list`, `--restore ID`, `--purge ID` and `--empty`.
- **VS Code: a Deleted group** at the bottom of the panel lists what is in the bin, with
  **Restore** and **Delete for good…** on each and **Empty the bin…** on the group. The
  search box covers it too.
- `claude-delete` and **Delete session…** no longer offer a session that is open in a
  running Claude process but idle. Before, only "written in the last two minutes" held
  it back. Running sessions are read from Claude Code's own `sessions/<pid>.json` records
  and from the command lines of the Claude program itself (`claude --resume ID`) — not
  from other commands that mention a session id, such as `claude-delete ID` checking it.

## [2.12.0] — 2026-09-23

- **Transcripts are kept.** Claude Code deletes transcripts after 30 days unless
  `cleanupPeriodDays` says otherwise, and they are the audit trail: the audit, weekly
  review, recap, search and sidebar all read them. `install.sh` now sets
  `"cleanupPeriodDays": 3650` in each profile's `settings.json` when it isn't set
  (backing the file up, keeping its permissions), and warns when a shorter value is set.

## [2.11.0] — 2026-09-23

- **`claude-delete`**: move a session with no value to the Trash — one with no
  artifacts, or one kept out of the review (`-n` / `no-audit.txt`). Never one the weekly
  review booked or one active in the last two minutes. It says what deleting means before
  asking (conversation gone, time leaving the audit, files it produced staying, request
  folder going if left empty), and takes the transcript's copies and Claude Code's
  per-session data with it. `--check`, `--json`, `--yes`.
- **VS Code: Delete session…** on the sessions that qualify, with that summary in a
  confirmation dialog; closes the session's tab.
- `claude-sessions --json` adds `audited`, `artifacts` and `deletable` (with why / why not)
  to each session.

## [2.10.0] — 2026-09-23

- **VS Code: pin sessions and requests.** Right-click → **Pin**, or the pin icon on hover.
  Pinned items get a **Pinned** group at the top of the panel, whatever the grouping and
  sort, and keep their place below with a pin mark. A pinned request brings its sessions
  and files. The search box and sort apply to the group too.
- Pins are kept in `<work root>/_config/pinned.json`, so they sync with the work root; a
  change made on another machine shows up without a reload.

## [2.9.0] — 2026-09-23

- **VS Code: sort the sessions.** A Sort button in the Work sessions panel: **last
  activity** (as before — resuming a session moves it up), **started** (newest first, so
  resuming moves nothing) or **name**. Remembered, and shown next to the grouping.
- **By day** always lists days newest first, with the work root last; before, a day moved
  up whenever one of its sessions was resumed.
- `claude-sessions --json` adds `started` for each session (its first transcript
  timestamp) and each request (`started_at` from `.session.json`, else its folder name).

## [2.8.0] — 2026-09-23

- **Copy for email.** New `claude-md-email FILE.md` renders Markdown with pandoc and
  `md-email.css` and puts it on the clipboard ready to paste into Outlook — black on
  white, whatever the editor's theme (a dark VS Code preview used to paste white text).
  Styles are inlined, since Outlook drops `<style>` blocks. `--open` and `--html` for a
  page instead. In VS Code: **Copy for email** on Markdown files, their preview, the
  Explorer and the sidebar's Files.
- `pandoc` is now installed with the base prerequisites, not only with the yazi extras.

## [2.7.0] — 2026-09-23

- **VS Code: a request's files in the sidebar.** Each request has a **Files** entry with
  its folder's contents as a tree (hidden files, `.git`, `node_modules`, `__pycache__` and
  virtualenvs left out). Click to open — Markdown in the preview — or right-click to
  reveal in Finder or copy the path. The search box matches file names too, and narrows
  the Files to the matches. Hovering a session lists the files it wrote.
- `claude-sessions --json` adds each request's `files` and each session's `written` files,
  from its Write / Edit / MultiEdit / NotebookEdit tool calls. Transcripts are read
  incrementally, with the position cached in `~/.cache/claude-worksessions/written.json`.

## [2.6.0] — 2026-09-22

- **VS Code: the terminal commands and your skills in the Command Palette** (*Work
  sessions: …*): recent sessions, search (plain and `--ai`), audit, set task type, go to
  request, resume by id, and **Run skill…**, which starts any skill in `~/.claude-*/skills`
  as a new request. Right-click a session or request for the ones that apply to it.
- **VS Code: a search box above the sessions.** Typing filters the tree; Enter searches
  inside the conversations with `claude-search`.
- `claude-new --prompt TEXT` starts Claude with a first prompt (`--prompt /weekly-review`).

## [2.5.0] — 2026-09-22

- `claude-new` asks whether the session counts in the weekly review and daily recap
  (`[Y/n]`, Enter for yes) unless `-n` or the new `-a` / `--audit` answers it. Until now
  only `-n` could leave a session out, so a session started without it — such as from
  the VS Code sidebar's **+**, which runs plain `claude-new` — always counted.

## [2.4.0] — 2026-09-22

- **Work sessions sidebar for VS Code.** `install.sh` builds and installs a small
  extension (no npm; `vscode/package_vsix.py` packages it) when `code` is on the PATH.
  It lists your requests and their Claude sessions, grouped by day, by ticket, or as a
  flat recent list, and opens each session as a terminal tab in the editor area, in its
  own folder with its own profile. New request (`claude-new`) and new session in a request
  are one click; tabs are named `TICKET · title` and survive a window reload.
  See [docs/commands.md](docs/commands.md#vs-code-sidebar).
- `claude-sessions --json`: each session with its auto-title, latest prompt and request
  folder (name, ticket, task type, profile). The sidebar reads this.
- `uninstall.sh` removes the sidebar and the `claudeCode.claudeProcessWrapper` setting
  with `claude-vscode`, and no longer fails to clean `~/.zshrc` (it used `$PY` without
  setting it).
- The extension's logic has `node --test` tests, run by pytest when node is installed.

## [2.3.0] — 2026-09-22

- **VS Code.** The Claude extension now runs with the profile of the request folder it
  is opened on.
  - New `claude-vscode`, which `install.sh` sets as the extension's
    `claudeCode.claudeProcessWrapper`. It reads `profile` from the folder's
    `.session.json` (or the nearest one above) and sets `CLAUDE_CONFIG_DIR` to match;
    outside a request folder it changes nothing. The extension's own env setting is
    machine-wide, so it couldn't do this per folder.
  - `install.sh` writes that setting to VS Code's user settings (the remote machine
    settings on WSL), backing the file up first. If the file has comments or trailing
    commas it leaves it alone and prints the line to add.
  - `claude-new -c` / `--code` creates the folder and `.session.json` as usual, then
    opens the folder in a new VS Code window instead of starting Claude in the terminal.

## [2.2.0] — 2026-09-22

- New `claude-sessions` command, installed with the others: the most recent sessions
  across all profiles, one line each (`claude-sessions [N]`, `-a` for all). It replaces
  a stand-alone script of the same name in `~/.local/bin`, which `install.sh` backs up
  and links over. Unlike that script it:
  - lists each session once. Moving a folder leaves a copy of its transcripts under the
    old path's project dir, so moved sessions used to appear twice.
  - shows moved folders where they are now, through `_audit/moved-folders.json`, instead
    of the flat `YYYY-MM-DD_slug` path they ran in.
  - reads every profile in `CWS_PROFILES`, not just `~/.claude-personal`.

## [2.1.0] — 2026-09-22

- Runs on **Linux** and on **Windows through WSL**, as well as macOS.
  - `install.sh` detects the system. On Linux/WSL it installs packages with `apt`,
    `dnf`, `pacman` or `zypper` (or Homebrew, if present), one at a time, and says
    where to get `yazi` / `glow` when the distribution doesn't carry them. It warns
    when the login shell isn't zsh, and says to use zsh when run under bash.
  - On WSL the work root defaults to the Windows OneDrive folder, and the Outlook
    time-zone name is read from Windows.
  - `claude-audit --copy` uses `clip.exe` on WSL (as UTF-16, so accents survive), and
    `wl-copy`, `xclip` or `xsel` on Linux.
  - `ws -o` and the yazi *Open as HTML* opener use Explorer on WSL and `xdg-open` on Linux.
  - Scripts start with `#!/usr/bin/env zsh`, since zsh isn't always at `/bin/zsh`.
- CI runs the tests on Ubuntu and macOS, and does a real install on a clean Ubuntu.

## [2.0.1] — 2026-09-22

- `install.sh` printed stray `p=work` and `f=config/config.example.env` lines: two
  top-level loop variables were re-declared by a later `local`, which makes zsh print
  them. The loops now use their own names.

## [2.0.0] — 2026-09-22

- **Breaking:** `claude-new`'s `-w` / `--work`, `-p` / `--personal` and `-P` are gone.
  `-p NAME` / `--profile NAME` now takes any profile in `CWS_PROFILES`, so adding a
  profile needs no code change. Replace `claude-new -w ...` with `claude-new -p work ...`.
  An unknown or missing name is an error that lists the valid ones.
- **Breaking:** the per-profile aliases `claude-personal`, `claude-work`, … are gone.
  Use `claude-resume -p NAME [claude args]` — `claude-work --resume ID` becomes
  `claude-resume -p work --resume ID`. With no claude arguments it opens the resume
  picker. `claude-search` prints and runs resume commands this way, and now sets the
  config dir for every configured profile, not just `work` / `personal`.
- Profile names can no longer contain dashes. `CWS_PROFILE_my-work_DESC` / `_BASE_URL`
  are not valid variable names, so they were silently ignored — a gateway profile named
  `my-work` lost its URL and was set up as a subscription login. `install.sh --profiles`
  now asks for letters, digits and underscores, and `install.sh` stops if `CWS_PROFILES`
  holds a dashed name (rename it, e.g. `my_work`, and its `~/.claude-<name>` folder).
- `claude-new -L` / `--profiles` lists the configured profiles: default and shared
  markers, description, gateway URL, and a warning when `~/.claude-<name>` is missing.

## [1.9.2] — 2026-09-21

- Test suite (`tests/`, pytest) and a `tests` GitHub Actions workflow on every pull
  request. It fails if line coverage of `bin/` drops below 95%.
- Changes, releases included, now go through pull requests; `docs/releasing.md` updated.
- Merging a PR that bumps `VERSION` tags `vX.Y.Z` and publishes the release automatically
  (`release` workflow).

## [1.9.1] — 2026-09-21

- `claude-new`'s task-type menu showed only the first 8 types, so once 8 were in use the
  unused seeds from `CWS_TASK_TYPES` (e.g. `documentation`, `tickets`) never appeared.
  It now lists every type: used ones first, newest first, then the unused seeds.

## [1.9.0] — 2026-09-21

- Sessions that ran outside a request folder (in a repo, the work root or at home) can
  now be attributed to one: map session id → request folder in
  `_audit/session-folders.json`. `claude-audit` falls back to that map when the folder a
  session ran in has no `.session.json`, so ticket, profile and task type resolve for
  work done in a repo — without moving anything or touching the repo.

## [1.8.1] — 2026-09-21

- The "type the trigger, not the detours" wording that 1.8.0's notes promised: it only
  reached the changelog, not CLAUDE.md, the skills or the docs. Now in all four.

## [1.8.0] — 2026-09-21

- When nothing in the session name matches a known type, `claude-new` no longer falls
  back to your most recent type: it says so and asks you to pick from the list (or type
  your own, or `-` for none).

## [1.7.0] — 2026-09-21

The task type is now **per session**, not per request folder.

- `.session.json` keeps `task_type` as the folder's default and gains `session_types`,
  mapping a session id to its own type. A session's own type wins.
- `claude-type <type>` sets it for the running session (identified by its transcript);
  `claude-type --folder <type>` sets the folder default. With no argument it shows the
  current type and which of the two it came from.
- `claude-audit` resolves each session's type the same way, so resuming a folder for a
  different kind of work no longer mislabels it — or the folder's other sessions.
- Known limit: a resumed session keeps one id across days, so its type covers the whole
  session rather than a single day's part of it.

## [1.6.0] — 2026-09-20

- `claude-audit --with-type` includes the Task Type column in `--copy` as well, for a
  tracker that has gained the column; `--no-type` leaves it out of the table, the CSV
  and the clipboard. The default is unchanged: shown on screen and in the CSV, never
  pasted.

## [1.5.0] — 2026-09-20

Every session now records **what kind of work it is**.

- `.session.json` gains `task_type` (permissions, job errors, new features, security,
  …). `claude-new` guesses one from the session name, offers the types already in use,
  and takes anything you type; `-T type` skips the prompt.
- `claude-type` shows or changes it mid-session, from anywhere inside the session
  folder. CLAUDE.md tells Claude to change it — and say so — when the subject shifts.
- `claude-type --backfill` guesses types for older sessions; it only writes with
  `--apply`.
- `claude-audit`: `task_type` column in the sessions and detail CSVs, a `Task Type`
  column in the weekly table and CSV (never in `--copy`, which must match the
  tracker's columns), `task_types` in the breakdown, and a new `--by-type` view with
  hours per type.
- The daily recap reports where the time went by type; the weekly review uses type as
  supporting evidence and reports the week's split.

## [1.4.1] — 2026-09-20

- `docs/folder-layout.md`: when request folders move, **rename** the Claude history
  directory to the new path and leave the old name as the symlink — not the other way
  round. A symlinked project directory makes tools that write beside the transcripts
  fail: large MCP results are saved to `<project dir>/<session id>/tool-results/`, and
  that write is refused when the project dir is a link.

## [1.4.0] — 2026-09-20

- The standing context is now **copied into** the work root's `CLAUDE.md` instead of
  imported with `@_config/context.md`. Claude Code does not expand an `@import` in a
  parent `CLAUDE.md` for a session running in a sub-folder — and every session runs
  several folders down, so the context silently never loaded. Verified by running a
  throwaway session from a request folder and asking for facts only the context holds.
- Editing `_config/context.md` now needs `./install.sh` to regenerate `CLAUDE.md`.

## [1.3.2] — 2026-09-20

Fixes found while installing on a live machine.

- A render that fails (missing template, unset `{{KEY}}`) no longer replaces the
  target with an empty file — it warns and leaves the existing file alone.
- `install.sh` refuses to run if its own folder isn't a claude-worksessions
  checkout, and stops if the shell library can't be loaded, instead of carrying on
  with whatever `CLAUDE_WORK_ROOT` happened to be in the environment.

## [1.3.1] — 2026-09-20

- `--profiles` now backs up `config.env` before the answers overwrite it, so a
  reconfigure can be undone like everything else install.sh replaces.
- Rolling back to an older release says so instead of printing that release's
  changelog as if it were news.

## [1.3.0] — 2026-09-20

Updating in place.

- `install.sh --update` fetches, moves the checkout to the newest release and
  re-installs, so the skills and `CLAUDE.md` are re-rendered rather than drifting.
  `--update vX.Y.Z` pins or rolls back; `--edge` follows main.
- It stops rather than discarding anything if the checkout has local changes, and
  prints the changelog entries between the old and new version.
- A normal run notes when a newer release exists, fetching at most once a day.

## [1.2.0] — 2026-09-20

Setup asks instead of expecting a hand-edited config.

- First run is a wizard: work root, org, role, time zone (guessed from the Mac),
  Outlook's name for it, example ticket key, Atlassian cloud id, Markdown extras.
- Profiles are prompted for: any number, each a Claude subscription (sign-in offered)
  or an inference gateway (base URL + token, no login needed). It also asks which is
  the default and which owns the shared history.
- `install.sh --profiles` re-runs the profile questions; stale profile settings are
  dropped from the config, and a dropped profile's `~/.claude-<name>` is left in place.
- No more "edit the file and run it again" step.

## [1.1.0] — 2026-09-20

The installer no longer assumes anything is set up first.

- Bootstraps a clean Mac: lists what's missing (Xcode Command Line Tools, Homebrew,
  Claude Code, brew packages), asks once, installs it, and adds Homebrew to
  `~/.zprofile`. `--no-bootstrap` reports without installing.
- Offers to open each profile so you can sign in, and remembers it did. A profile on
  an API gateway is skipped — its token is enough.
- No longer needs `/usr/bin/python3`: the system Python is preferred, otherwise any
  `python3`, otherwise Homebrew's — so Command Line Tools are not a hard requirement.
- Docs say what stays outside the package: claude.ai connectors (they follow your
  login) and any local MCP servers.

## [1.0.0] — 2026-09-18

First packaged release of a setup that grew by hand.

- `claude-new`: request folders as `YYYY/MM/DD/HH-mm-ss_slug`, mandatory ticket,
  profile menu built from the config, `--no-audit`, `-l`.
- `claude-<profile>` aliases for any number of profiles; non-shared profiles share
  history, projects, skills, plugins and MCP with the shared one.
- `claude-audit` and `claude-search` read the config (work root, profiles, org) and
  resolve moved folders through `_audit/moved-folders.json`.
- `weekly-review` and `workday-recap` skills, rendered from templates; personal house
  rules moved out to `_config/review-rules.md`.
- Work-root `CLAUDE.md` generated from a template, importing `_config/context.md`.
- `ws` and `y` navigation; yazi with glow preview and Markdown → HTML for email.
- `install.sh` (idempotent, `--dry-run`, backups) and `uninstall.sh`.
