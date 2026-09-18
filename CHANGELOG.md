# Changelog

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
