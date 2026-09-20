# Changelog

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
