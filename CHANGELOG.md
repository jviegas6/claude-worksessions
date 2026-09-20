# Changelog

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
