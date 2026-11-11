# claude-worksessions

A Claude Code work setup for macOS, Linux and Windows (WSL): every request in its own dated folder,
opened in whatever app runs Claude for you (T3 Code by default), a time audit built from the
transcripts, search across past sessions — all driven by one config file. Skills (a weekly review, a daily recap…)
are not part of it: install them separately, e.g. with Skillshare; they read the same config file.

| piece | what it does |
|---|---|
| `claude-new` | creates `YYYY/MM/DD/HH-mm-ss_slug/`, records the ticket and task type in `.session.json`, then opens it with `CWS_OPEN_CMD`, one line in the config: by default [T3 Code](https://github.com/pingdotgg/t3code), as `TICKET · date · name`; another app is another line, not new code |
| `claude-t3-sync` | titles every request folder's T3 Code project by its ticket, and removes empty, idle ones; shows the changes first, `--apply` makes them, `--undo` puts them back |
| `claude-area` | the request's place in T3 Code's sidebar, its project and type: `claude-new` chooses them from the ticket, name and goal, and `claude-area` changes them without touching the folder or a running thread |
| VS Code sidebar | requests and their sessions by day or ticket, each session opened as a tab in its own folder |
| `claude-wait` | who the ball is with, per request: a flag in `.session.json` and notes in `thread.md` |
| `claude-resume` | Claude Code, resuming: `claude-resume --resume ID`; no args opens the session picker |
| `claude-audit` | what you worked on — per day, week, month — from transcripts plus meetings/mail/chats |
| `claude-search` | find past sessions by ticket or topic, with the command to resume each |
| `claude-sessions` | the most recent sessions across every Claude config dir (`CWS_CLAUDE_HOMES`): when, id, folder, first prompt |
| `claude-delete` | move a session with no value (no artifacts, or started with `-n`) to a bin you can restore from, after saying what that means — also **Delete session…** in VS Code |
| prompt-quality hooks | Claude asks first when a request is vague or something it was asked about doesn't exist (opt-in, `CWS_HOOKS="1"`) |
| `claude-guard` | keeps a session on its goal: flags (or blocks) pivots to a new objective, reads outside the request's scope and repeated calls, and asks for next-level proposals instead of doing them; `claude-goal` re-anchors |
| `claude-retro` | a retrospective on your prompts: where work stalled (a resource that didn't exist, corrections, interruptions, clarifying questions), whether the prompt caused it, and a better version — with a trend from week to week |
| `claude-md-email` | a Markdown file onto the clipboard, formatted for email (black on white, Calibri, bordered tables) — also **Copy for email** in VS Code |
| `ws` / `y` | fuzzy-jump to a request folder; browse it in yazi |
| yazi extras | rendered Markdown preview, `Enter` on a `.md` opens it as HTML for pasting into email |

## Install

```sh
git clone https://github.com/jviegas6/claude-worksessions.git ~/Repos/claude-worksessions
cd ~/Repos/claude-worksessions
./install.sh            # asks where the work root goes and a few settings
source ~/.zshrc
```

Since 3.0.0 this is not a Claude Code plugin and ships no skills. A `worksessions` plugin left
by 2.35–2.38 is removed by `uninstall.sh`, or by hand: `claude plugin uninstall
worksessions@claude-worksessions` per Claude config dir, or `skillshare plugin remove worksessions`.

Since 3.1.0 it has no profiles: the app that runs Claude (T3 Code's providers, an IDE) decides
which login a session uses. `CWS_CLAUDE_HOMES` only says where their transcripts are.

On a clean **Mac** the installer lists what is missing — Xcode Command Line Tools,
Homebrew, Claude Code, `fzf`, `pandoc` (for `claude-md-email`), and `yazi glow` for the Markdown extras — asks
once, and installs the lot. Signing in to Claude is the app's business (T3 Code, an IDE, or `claude`).

On **Linux**, install zsh and git first (`sudo apt install zsh git`, or your
distribution's equivalent), then run `zsh ./install.sh`. Packages come from `apt`,
`dnf`, `pacman` or `zypper` (or Homebrew, if you have it). `yazi` and `glow` aren't in
every distribution's repositories; when one can't be installed the installer says
where to get it. If your login shell isn't zsh, it tells you to run `chsh -s $(which zsh)`.

On **Windows**, use WSL: `wsl --install -d Ubuntu`, then follow the Linux steps
inside Ubuntu. The work root defaults to your Windows OneDrive folder
(`/mnt/c/Users/<you>/OneDrive - <org>/work_sessions`), so it syncs as it does on a
Mac. Keep the checkout and your Claude config dirs in the Linux home (`~`), not under
`/mnt/c` — file access across the two is slow. `--copy` uses the Windows clipboard,
and HTML / `ws -o` open in Windows.

- `--update` moves the checkout to the newest release and re-installs (`--update vX.Y.Z` for a specific one, `--edge` to follow main)
- `--dry-run` shows what it would change and changes nothing
- `--no-bootstrap` installs nothing, only reports what's missing
- `--yes` never prompts

Re-running is safe: unchanged things are left alone, anything replaced is backed up as
`*.bak-<timestamp>`.

The first run asks the questions instead of making you edit a file: work root, org,
role, time zone (guessed from the system), example ticket key, and the Claude config dirs
whose transcripts are read. `./install.sh --reconfigure` asks again.

Two things stay outside the package: **connectors** (Atlassian and Microsoft 365, for
the skills you install) come with your Claude account once you sign in, and any
**local MCP servers** you use are configured in Claude Code itself.

## Configure

Everything specific to you lives in `<work root>/_config/`, not in this repo:

| file | holds |
|---|---|
| `config.env` | work root, org, time zone, ticket format, Jira cloud id, Claude config dirs, how a request opens |
| `context.md` | standing context every session starts with — tenants, subscriptions, workspaces, repos |
| `review-rules.md` | your weekly-review house rules — default task, catch-all epics, tickets to ignore |
| `guard-rules.md` | what `claude-guard`'s judge counts as a pivot |

Put the work root in a synced folder (OneDrive, iCloud) and your config travels with
it. See [docs/configuration.md](docs/configuration.md).

## Docs

- [User guide](docs/user-guide.md) — how to use it, task by task
- [High-Level Design](docs/hld.md) and [Low-Level Design](docs/lld.md) — how it works
- [Configuration](docs/configuration.md) — every setting, and how a request opens
- [Commands](docs/commands.md) — `claude-new`, `claude-audit`, `claude-search`, `claude-sessions`, the VS Code sidebar, `ws`, `y`, yazi keys
- [Folder layout](docs/folder-layout.md) — what goes where, and moving folders safely
- [claude-guard](docs/guard/user-guide.md) — keeping sessions on their goal: [user guide](docs/guard/user-guide.md), [HLD](docs/guard/hld.md), [LLD](docs/guard/lld.md)
- [New computer](docs/new-computer.md) — moving the whole setup
- [Releasing](docs/releasing.md) — versions, tags and GitHub releases
- [Changelog](CHANGELOG.md)
