# claude-worksessions

A Claude Code work setup for macOS: every request in its own dated folder, several
Claude profiles sharing one history, a time audit built from the transcripts, search
across past sessions, and daily/weekly review skills — all driven by one config file.

| piece | what it does |
|---|---|
| `claude-new` | creates `YYYY/MM/DD/HH-mm-ss_slug/`, records profile + ticket in `.session.json`, starts Claude there |
| `claude-<profile>` | Claude Code with that profile (`claude-personal`, `claude-work`, …) |
| `claude-audit` | what you worked on — per day, week, month — from transcripts plus meetings/mail/chats |
| `claude-search` | find past sessions by ticket or topic, with the command to resume each |
| `ws` / `y` | fuzzy-jump to a request folder; browse it in yazi |
| `weekly-review` skill | fills the weekly tracker, asking only about what's new |
| `workday-recap` skill | reconstructs a day from Claude, Teams, calendar and sent mail |
| yazi extras | rendered Markdown preview, `Enter` on a `.md` opens it as HTML for pasting into email |

## Install

```sh
git clone https://github.com/jviegas6/claude-worksessions.git ~/Repos/claude-worksessions
cd ~/Repos/claude-worksessions
./install.sh            # first run creates <work root>/_config/config.env — edit it
./install.sh            # second run installs
source ~/.zshrc
```

Needs macOS, zsh, Homebrew, Python 3 (the system one is fine) and
[Claude Code](https://docs.claude.com/claude-code). `install.sh` brew-installs
`fzf`, and `yazi glow pandoc` when the yazi extras are on.

`./install.sh --dry-run` shows what it would change. Re-running is safe: unchanged
things are left alone, anything replaced is backed up as `*.bak-<timestamp>`.

## Configure

Everything specific to you lives in `<work root>/_config/`, not in this repo:

| file | holds |
|---|---|
| `config.env` | work root, org, time zone, ticket format, Jira cloud id, profiles, gateway URL |
| `context.md` | standing context every session starts with — tenants, subscriptions, workspaces, repos |
| `review-rules.md` | your weekly-review house rules — default task, catch-all epics, tickets to ignore |

Put the work root in a synced folder (OneDrive, iCloud) and your config travels with
it. See [docs/configuration.md](docs/configuration.md).

## Docs

- [Configuration](docs/configuration.md) — every setting, profiles, gateway tokens
- [Commands](docs/commands.md) — `claude-new`, `claude-audit`, `claude-search`, `ws`, `y`, yazi keys
- [Folder layout](docs/folder-layout.md) — what goes where, and moving folders safely
- [New computer](docs/new-computer.md) — moving the whole setup
- [Releasing](docs/releasing.md) — versions, tags and GitHub releases
- [Changelog](CHANGELOG.md)
