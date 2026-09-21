# Changelog

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
