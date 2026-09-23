# claude-worksessions

A Claude Code work setup for macOS, Linux and Windows (WSL): every request in its own dated folder, several
Claude profiles sharing one history, a time audit built from the transcripts, search
across past sessions, and daily/weekly review skills — all driven by one config file.

| piece | what it does |
|---|---|
| `claude-new` | creates `YYYY/MM/DD/HH-mm-ss_slug/`, records profile + ticket in `.session.json`, starts Claude there |
| `claude-new -c` | the same, then opens the folder in VS Code, where the Claude extension uses the session's profile |
| VS Code sidebar | requests and their sessions by day or ticket, each session opened as a tab in its own folder and profile |
| `claude-resume` | Claude Code with a profile: `claude-resume -p work --resume ID`; no args opens the session picker |
| `claude-audit` | what you worked on — per day, week, month — from transcripts plus meetings/mail/chats |
| `claude-search` | find past sessions by ticket or topic, with the command to resume each |
| `claude-sessions` | the most recent sessions across all profiles: when, id, folder, first prompt |
| `claude-delete` | move a session with no value (no artifacts, or started with `-n`) to the Trash, after saying what that means — also **Delete session…** in VS Code |
| `claude-md-email` | a Markdown file onto the clipboard, formatted for email (black on white, Calibri, bordered tables) — also **Copy for email** in VS Code |
| `ws` / `y` | fuzzy-jump to a request folder; browse it in yazi |
| `weekly-review` skill | fills the weekly tracker, asking only about what's new |
| `workday-recap` skill | reconstructs a day from Claude, Teams, calendar and sent mail |
| yazi extras | rendered Markdown preview, `Enter` on a `.md` opens it as HTML for pasting into email |

## Install

```sh
git clone https://github.com/jviegas6/claude-worksessions.git ~/Repos/claude-worksessions
cd ~/Repos/claude-worksessions
./install.sh            # asks where the work root goes, then about your profiles
source ~/.zshrc
```

On a clean **Mac** the installer lists what is missing — Xcode Command Line Tools,
Homebrew, Claude Code, `fzf`, `pandoc` (for `claude-md-email`), and `yazi glow` for the Markdown extras — asks
once, and installs the lot. It then offers to open each profile so you can sign in.

On **Linux**, install zsh and git first (`sudo apt install zsh git`, or your
distribution's equivalent), then run `zsh ./install.sh`. Packages come from `apt`,
`dnf`, `pacman` or `zypper` (or Homebrew, if you have it). `yazi` and `glow` aren't in
every distribution's repositories; when one can't be installed the installer says
where to get it. If your login shell isn't zsh, it tells you to run `chsh -s $(which zsh)`.

On **Windows**, use WSL: `wsl --install -d Ubuntu`, then follow the Linux steps
inside Ubuntu. The work root defaults to your Windows OneDrive folder
(`/mnt/c/Users/<you>/OneDrive - <org>/work_sessions`), so it syncs as it does on a
Mac. Keep the checkout and your Claude profiles in the Linux home (`~`), not under
`/mnt/c` — file access across the two is slow. `--copy` uses the Windows clipboard,
and HTML / `ws -o` open in Windows.

- `--update` moves the checkout to the newest release and re-installs (`--update vX.Y.Z` for a specific one, `--edge` to follow main)
- `--dry-run` shows what it would change and changes nothing
- `--no-bootstrap` installs nothing, only reports what's missing
- `--yes` never prompts (skips the gateway token and the sign-in offer)

Re-running is safe: unchanged things are left alone, anything replaced is backed up as
`*.bak-<timestamp>`.

The first run asks the questions instead of making you edit a file: work root, org,
role, time zone (guessed from the system), example ticket key, and then your profiles —
as many as you want, each either a **Claude subscription** (you sign in) or an
**inference gateway** (base URL + token). `./install.sh --profiles` changes them later.

Two things stay outside the package: **connectors** (Atlassian for the weekly review,
Microsoft 365 for the recap) come with your Claude account once you sign in, and any
**local MCP servers** you use are configured in Claude Code itself.

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
- [Commands](docs/commands.md) — `claude-new`, `claude-audit`, `claude-search`, `claude-sessions`, the VS Code sidebar, `ws`, `y`, yazi keys
- [Folder layout](docs/folder-layout.md) — what goes where, and moving folders safely
- [New computer](docs/new-computer.md) — moving the whole setup
- [Releasing](docs/releasing.md) — versions, tags and GitHub releases
- [Changelog](CHANGELOG.md)
