# claude-worksessions — Low-Level Design

| | |
|---|---|
| System | claude-worksessions |
| Version | 2.16.1 |
| Companion documents | [High-Level Design](hld.md) · [User guide](user-guide.md) · [claude-guard LLD](guard/lld.md) |

This document describes the implementation as it is. Function names refer to the file named
in each section's title.

- [1. Repository layout and conventions](#1-repository-layout-and-conventions)
- [2. Configuration](#2-configuration)
- [3. Installation](#3-installation)
- [4. Shell functions](#4-shell-functions-shellworksessionszsh)
- [5. Data formats](#5-data-formats)
- [6. claude-audit](#6-claude-audit)
- [7. claude-sessions](#7-claude-sessions)
- [8. claude-search](#8-claude-search)
- [9. claude-delete](#9-claude-delete)
- [10. claude-retro](#10-claude-retro)
- [11. Hooks and claude-guard](#11-hooks-and-claude-guard)
- [12. Output utilities](#12-output-utilities)
- [13. VS Code extension](#13-vs-code-extension-vscode)
- [14. Skills](#14-skills)
- [15. Known limitations](#15-known-limitations)
- [16. CI, release and tests](#16-ci-release-and-tests)

---

## 1. Repository layout and conventions

| Path | Contents |
|---|---|
| `bin/` | the commands. Python 3 (standard library only). Symlinked into `~/.local/bin` |
| `shell/worksessions.zsh` | zsh functions, sourced from a managed block in `~/.zshrc` |
| `install.sh`, `uninstall.sh` | zsh; set up and remove everything outside the repo |
| `config/*.example.*` | seeds for `<work root>/_config/` |
| `templates/CLAUDE.md.tmpl` | the work root's `CLAUDE.md` |
| `vscode/` | the sidebar extension (`extension.js`, `model.js`, `package.json`, `package_vsix.py`, `test/`) |
| `yazi/` | yazi config template, glow styles, `md-email.css`, `md2html.sh` |
| `tests/` | pytest suite; `vscode/test/` node tests run from `tests/test_vscode.py` |
| `docs/` | this document, the HLD, user guide, command reference, configuration, folder layout, releasing, and `guard/` |
| `VERSION`, `CHANGELOG.md` | release metadata (§16) |

**Module loading.** Python commands don't `import` each other. A loader function
(`load_audit`, `load_sessions`) uses `importlib.machinery.SourceFileLoader` on the sibling script
next to `realpath(__file__)`, falling back to `~/.local/bin/<name>`:

- `claude-sessions`, `claude-search` → `claude-audit` (as `CA`)
- `claude-delete`, `claude-retro` → `claude-sessions` (as `CS`), and `CS.CA`

Importing `claude-audit` runs `load_config()` and fixes every path (`DEFAULT_ROOT`, `LEDGER_PATH`,
…) at import time, which is why the tests re-import scripts per test.

**Conventions.** Atomic writes use `<file>.tmp` + `os.replace`. Timestamps written by the shell
are UTC ISO-8601 with `Z`; folder names and audit days use local time. Stable ids are
`prefix + sha1(parts joined by \x1f)[:10]`.

---

## 2. Configuration

### 2.1 Location

`<work root>/_config/config.env`, linked from `~/.config/claude-worksessions/config.env`.
`$CWS_CONFIG` overrides the path for every reader.

### 2.2 Readers

| Reader | Accepts | Values | Precedence |
|---|---|---|---|
| zsh `_cws_load_config` (`shell/worksessions.zsh` L10–30) | `^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$`, any variable name | quoted: up to the first closing quote; bare: ` # comment` and trailing blanks removed; `$HOME`/`${HOME}` expanded | **the file overwrites** an environment variable of the same name (`typeset -g`) |
| Python `load_config` (`claude-audit`, `claude-guard`) | `^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$` (an `export KEY=` line doesn't match) | same rules | **`CWS_*` environment variables override** the file |
| VS Code `config()` (`extension.js`) | `^\s*([A-Za-z_][A-Za-z0-9_]*)=["']?([^"'#\n]*)["']?` | stops at `#` or a quote; `$HOME` expanded | file only |

A missing file leaves the defaults.

### 2.3 Keys

| Key | Default | Consumers |
|---|---|---|
| `CWS_WORK_ROOT` | `$HOME/work_sessions` (fallback `CLAUDE_WORK_ROOT`) | all |
| `CWS_ORG` | empty | skills (read from `config.env` at run time); `claude-audit` adds its words to `STOPWORDS` |
| `CWS_USER_ROLE` | `data/platform engineer` (installer default) | skills; `claude-retro` judge prompt |
| `CWS_TIMEZONE` / `CWS_TIMEZONE_WINDOWS` | `UTC` | skills (Outlook queries) |
| `CWS_TICKET_EXAMPLE` | `PROJ-123` | `claude-new` prompts, `CLAUDE.md`, skills |
| `CWS_JIRA_CLOUD_ID` | empty | weekly-review skill |
| `CWS_TASK_TYPES` | `permissions, job errors, new features, security, investigation, data quality, tooling, documentation` | `claude-new` task-type menu |
| `CWS_CLAUDE_HOMES` | `~/.claude` (else `~/.claude-<p>` per name in an old `CWS_PROFILES`) | transcript discovery (Python, shell, extension), installer (retention, hooks per dir), extension (watchers, skills) |
| `CWS_OPEN_CMD` | T3 (`claude-t3-sync --open {dir} --prompt {prompt}`) when an old `CWS_OPEN="t3"` is set and the line is missing; else empty | `claude-new`; `claude-search` (opens in T3 when it names `claude-t3-sync`) |
| `CWS_AFTER_NEW_CMD` | `claude-area --dir {dir} --pick {project} --type {type}` when the line is missing and `claude-area` is on PATH | `claude-new` |
| `CWS_INSTALL_YAZI` | `1` | installer |
| `CWS_GUARD_MODE`, `CWS_GUARD_MODEL`, `CWS_GUARD_CONFIG_DIR`, `CWS_GUARD_JUDGE_TIMEOUT`, `CWS_GUARD_IGNORE_NAMES`, `CWS_GUARD_MAX_EXTENSIONS` | `off` (`off`/`shadow`/`warn`/`enforce`), `haiku`, —, `25`, —, `2` | `claude-guard` ([LLD §2](guard/lld.md#2-configuration)) |

Environment-only: `CWS_CONFIG`, `CWS_PYTHON` (interpreter for shell JSON helpers), `CWS_OS`
(OS override), `CWS_CACHE_DIR`, `CWS_TRASH_DIR`, `XDG_CACHE_HOME`, `XDG_DATA_HOME`,
`CLAUDE_WORK_ROOT`, `CLAUDE_CONFIG_DIR`.

### 2.4 Other `_config/` files

| File | Seeded from | Read by |
|---|---|---|
| `context.md` | `config/context.example.md` | `install.sh` → inlined into `<work root>/CLAUDE.md` as `{{CONTEXT}}` |
| `review-rules.md` | `config/review-rules.example.md` | weekly-review skill |
| `guard-rules.md` | `config/guard-rules.example.md` | `claude-guard` judge |
| `pinned.json` | — | VS Code sidebar, `claude-delete` |

Seeds are copied only when the file is missing.

---

## 3. Installation

### 3.1 `install.sh` flags

| Flag | Effect |
|---|---|
| `--config FILE` | use this config |
| `--dry-run` | print `[dry-run] …` instead of changing anything |
| `--no-brew` | skip package and curl installs |
| `--no-bootstrap` | install nothing; report what's missing |
| `--reconfigure` | ask the basic settings again |
| `--update [vX.Y.Z]` | move the checkout to a release, then install |
| `--edge` | follow `main` |
| `--yes` / `-y` | never prompt |

Requires zsh (exits 1 otherwise). Backups are `<file>.bak-YYYYmmdd-HHMMSS`; symlinks are never
backed up.

### 3.2 Steps, in order

0. **Sanity.** The repo must contain `shell/worksessions.zsh`, `templates/CLAUDE.md.tmpl`,
   `bin/claude-audit` and `config/config.example.env`.
1. **Update** (with `--update`/`--edge`), `update_repo`: needs a clean checkout
   (`git status --porcelain` empty); `fetch --tags`; target = the given tag, `main`, or the newest
   `v*` tag (`sort -V`); checkout (`pull --ff-only` for main); prints the CHANGELOG sections gained.
2. **Configuration.** Resolves the config (existing link, `--config`, or asks for the work root).
   On first run copies the example with `CWS_WORK_ROOT` set, then (unless `--yes`/`--dry-run`)
   `configure_basics` (org, role, time zone, Windows zone name, example ticket, Atlassian cloud
   id, yazi extras, `CWS_CLAUDE_HOMES`).
   It then links `~/.config/claude-worksessions/config.env`, sources the shell file, takes the
   Claude config dirs from `CWS_CLAUDE_HOMES` (`~` expanded), and exports the render variables (`HOME`, `CWS_WORK_ROOT`, `CWS_ORG`,
   `CWS_USER_ROLE`, `CWS_TIMEZONE`, `CWS_TIMEZONE_WINDOWS`, `CWS_TICKET_EXAMPLE`, `CWS_JIRA_CLOUD_ID`).
3. **Prerequisites.** Wants `fzf pandoc` (+ `yazi glow` if `CWS_INSTALL_YAZI`, + `curl` off macOS),
   Command Line Tools and Homebrew on macOS, and Claude Code. One confirmation, then:
   `xcode-select --install` (polls up to 30 min), Homebrew's installer (adds `brew shellenv` to
   `~/.zprofile`), `curl -fsSL https://claude.ai/install.sh | bash`, and packages via `brew` or
   `apt-get`/`dnf`/`pacman`/`zypper` (sudo when not root). Python is re-resolved and installed if
   missing.
4. **Work root.** Creates the root, `_audit`, `_config`, `_daily`; seeds `_config/*.md`; renders
   `CLAUDE.md` with `CONTEXT=$(<_config/context.md)`.
5. **Claude config dirs** (§3.3): for each, **retention** and **hooks** (§3.4). Nothing is linked
   between them and nobody is signed in: logins are the app's (T3 Code's providers, an IDE).
6. **Commands.** Symlinks `claude-audit claude-search claude-sessions claude-md-email
   claude-delete claude-hook-notfound claude-hook-vague claude-guard claude-retro claude-t3-sync
   claude-area` into `~/.local/bin`; removes `claude-plan` and `claude-vscode` links into the
   checkout (gone in 3.0.0 / 3.1.0).
7. **VS Code.** Removes `claudeCode.claudeProcessWrapper` from the user `settings.json` when it
   still names `~/.local/bin/claude-vscode` (macOS `~/Library/Application Support/Code/User`, WSL
   `~/.vscode-server/data/Machine`, else `~/.config/Code/User`; a JSONC file naming it is
   reported, not edited). Installs the extension when `code --list-extensions --show-versions`
   differs from `VERSION` (§13.7).
8. **Hooks.** No plugin and no skills since 3.0.0. With `CWS_HOOKS=1` the six
   prompt-quality and guard entries are written into each config dir's `settings.json` (an older
   group holding only our hook is brought up to date); off, ours are removed.
9. **yazi** (if enabled). Renders `yazi.toml`, copies the glow styles, `md-email.css`,
    `md2html.sh`; installs the `piper` plugin.
10. **`~/.zshrc`.** A block between `# >>> claude-worksessions >>>` and `# <<< claude-worksessions <<<`
    with `PATH=$HOME/.local/bin:$PATH` and `source <repo>/shell/worksessions.zsh`. Identical →
    "block up to date"; different → replaced; absent → appended. Warns about legacy lines.
11. **Done.** Once a day, fetches tags and prints a notice when a newer release exists; warns if the
    login shell isn't zsh.

**Rendering** (`render SRC DST`): replaces `{{KEY}}` (`[A-Z_]+`) from the environment. A missing
key aborts that file and leaves the target untouched. Identical output → "unchanged"; otherwise
back up and write.

### 3.3 Claude config dirs

Each dir in `CWS_CLAUDE_HOMES` is created if missing and otherwise left as it is: links between
them made by releases before 3.1 (shared `projects`, `history.jsonl`, …) and `~/.claude` stay.

**Retention:** `cleanupPeriodDays` is set to 3650 where absent; a shorter explicit value is left
and warned about.

### 3.4 Hooks registered in every config dir's `settings.json`

| Event | Matcher | Command | Timeout (s) |
|---|---|---|---|
| `PostToolUse` | `Bash\|mcp__.*` | `~/.local/bin/claude-hook-notfound` | 10 |
| `PostToolUseFailure` | `Bash\|mcp__.*` | `~/.local/bin/claude-hook-notfound` | 10 |
| `UserPromptSubmit` | — | `~/.local/bin/claude-hook-vague` | 10 |
| `UserPromptSubmit` | — | `~/.local/bin/claude-guard prompt` | 30 |
| `PreToolUse` | `Read\|Glob\|Grep\|WebFetch\|WebSearch\|Bash\|Write\|Edit\|MultiEdit\|NotebookEdit\|mcp__.*` | `~/.local/bin/claude-guard tool` | 5 |
| `Stop` | — | `~/.local/bin/claude-guard stop` | 20 |

Added only when no hook in that event has the same `command`; the user's own hooks are kept. An
existing group holding only our hook gets its matcher updated when it differs.
Written atomically; invalid JSON is reported and left alone.

### 3.5 `uninstall.sh`

Removes: the `~/.local/bin` links that point into the repo (old `claude-plan`/`claude-vscode`
ones too); the `~/.zshrc` block (after a backup); the VS Code wrapper setting where it equals the
old `claude-vscode` path; the extension; our hook commands from `~/.claude/settings.json` and
every `~/.claude-*/settings.json` (dropping empty groups, events and `hooks`); a `worksessions`
plugin left by 2.35–2.38 and its marketplace, from every config dir; the config link. Keeps: the
work root, `_config/`, the Claude config dirs and history, links between them, retention, yazi
config, packages.

---

## 4. Shell functions (`shell/worksessions.zsh`)

On sourcing: loads the config (§2.2); sets `CWS_PYTHON` (`/usr/bin/python3`, else `python3`),
`CWS_CONFIG`, `CLAUDE_WORK_ROOT` (`CWS_WORK_ROOT` → `CLAUDE_WORK_ROOT` → `~/work_sessions`);
resolves `CWS_CLAUDE_HOMES` (else `~/.claude-<p>` per old `CWS_PROFILES` name, else `~/.claude`);
defaults `CWS_TICKET_EXAMPLE`, `CWS_TASK_TYPES`. It doesn't touch `CLAUDE_CONFIG_DIR` (before 3.1
it exported the default profile's).

### 4.1 `claude-new`

**Options** (parsed while the argument starts with `-`):

| Option | Effect |
|---|---|
| `-t/--ticket T` | ticket |
| `-T/--type T` | task type |
| `-g/--goal G`, `--done TEXT` | goal and done-when |
| `--path DIR` (repeatable) | a folder outside the request that is part of the work; must exist; stored absolute in `paths` |
| `-n/--no-audit`, `-a/--audit` | audit off; don't ask |
| `-A/--project P`, `-F/--front T` | `{project}`, `{type}` in `CWS_AFTER_NEW_CMD` (T3 sidebar placement) |
| `--prompt TEXT` | `{prompt}` in `CWS_OPEN_CMD` |
| `--new` | no offer to continue in a recent folder on the ticket |
| `-l/--list` | 15 newest request folders with `ticket type no-audit` |
| `-h/--help` | usage |

A first word shaped like a ticket (`^[A-Z][A-Z0-9]+-[0-9]+$`) is taken as the ticket when `-t` is
absent. The rest is the name.

**Prompts**, in order, each only when needed:

1. `Session name:` (blank is an error).
2. `Jira ticket (e.g. <example>, or Other):` — normalised by `_claude_new_ticket` (uppercased,
   spaces removed; `OTHER`/`NONE`/`-` → `Other`; else must match the ticket regex). Loops on a
   terminal; fails without one.
3. Task type (no `-T`): the guess from `_cws_guess_type` and the list from `_cws_task_types`
   (types used in past folders, newest first, then the seeds). Enter = guess, number = pick, `-` =
   none, other text = literal. Without a terminal: the guess.
4. `Goal — what should this session deliver? [name]:` and `Done when (Enter to skip):` (terminal
   only, no `-g`). Blank goal = name.
5. `Count it in the weekly review and daily recap? [Y/n]:` (terminal only, neither `-n` nor `-a`).

**Folder:** `$CLAUDE_WORK_ROOT/$(date +%Y/%m/%d/%H-%M-%S)_<slug>`. Slug: lowercase, non-`[a-z0-9]`
→ `-`, runs collapsed, trimmed, cut to 60, `session` if empty. An existing name gets `-2`, `-3`, …

**`.session.json`** (§5.1) written with indent 2. Prints `→ <ticket> [<type>] <relpath>`, `cd`s
in, runs `CWS_AFTER_NEW_CMD` (failure ignored), then `CWS_OPEN_CMD` (its status is `claude-new`'s;
empty → prints the folder path). `_cws_run_template` replaces `{dir} {title} {prompt} {project}
{type}` with `${(q)…}`-quoted values and `eval`s the result, so each value is one word and an
empty one is `''`. Continuing in a recent folder runs `CWS_OPEN_CMD` only. `ended_at` is never
written: nothing waits for the app. Removed in 3.1.0: `-p`, `-L`, `-c/--code`, `--cli`, `--t3`.

`_cws_guess_type` substring rules: permission/access/rbac/grant/entitlement → `permissions`;
error/fail/debug/broken/timeout/incident/outage → `job errors`; secret/security/vulnerab/gdpr/masking
→ `security`; duplicat/quality/reconcil/mismatch → `data quality`; migrat/build/implement/design/
setup/new → `new features`; doc/guide/runbook → `documentation`; investigat/analys/analyz/check/
audit/why → `investigation`.

### 4.2 `claude-resume [--] [claude args…]`

A leading `--` is dropped. No remaining arguments → `--resume` (the picker). Runs
`command claude "$@"` with the shell's own `CLAUDE_CONFIG_DIR`.

### 4.3 `claude-type`

- `claude-type` — prints the type and whether it's the session's or the folder's.
- `claude-type TYPE` — sets `session_types[<id>]` for the current session. The id is
  `_cws_session_id`: the most recently modified transcript under
  `~/.claude-*/projects/<folder path with non-alphanumerics → ->/`. No transcript → folder default,
  with a notice.
- `claude-type --folder TYPE` — sets the folder's `task_type`.
- `claude-type --backfill [--apply]` — guesses `task_type` for folders without one (fallback
  `investigation`); writes only with `--apply`.

The nearest `.session.json` is found by walking up from `$PWD` within the work root.

### 4.4 `claude-goal ["GOAL"] [--done "TEXT"]`

No arguments: prints goal and done-when. Otherwise appends `{goal, done_when, until}` to
`goal_history`, sets the new values, clears `literal`/`targets`/`open` for every session in the
folder's `.scope.json`, and appends a `goal` event to `.quality.jsonl`. See
[guard LLD §14.2](guard/lld.md#142-claude-goal).

### 4.5 Navigation

- `ws [-o|-c|-y]` — lists `YYYY/MM/DD/*` folders newest first, picks with
  `fzf --height=60% --reverse --preview "ls -la …"`, `cd`s in; `-o` opens in the OS file manager
  (`open`, `explorer.exe` via `wslpath -w`, `xdg-open`), `-c` in VS Code, `-y` in yazi.
- `y` — runs `yazi --cwd-file=<tmp>` and `cd`s to where yazi quit.

---

## 5. Data formats

### 5.1 `.session.json`

| Field | Set by | Notes |
|---|---|---|
| `name`, `slug` | `claude-new` | |
| `profile` | `claude-new` before 3.1 | ignored since 3.1 (the app picks the login) |
| `ticket` | `claude-new` | `PREFIX-123` or `Other` |
| `task_type` | `claude-new`, `claude-type --folder`, sidebar | the folder default |
| `session_types` | `claude-type`, sidebar | `{session id: type}`; wins over `task_type` |
| `goal`, `done_when`, `goal_history` | `claude-new`, `claude-goal` | read by `claude-guard` |
| `paths` | `claude-new --path`, `claude-goal --path` | folders in the request's scope for `claude-guard` |
| `audit` | `claude-new` | only literal `false` excludes |
| `started_at`, `ended_at` | `claude-new` | UTC; `ended_at` stays `null` for `-c` |
| `host`, `path` | `claude-new` | |

### 5.2 `_audit/` files

| File | Shape |
|---|---|
| `moved-folders.json` | `{old path: new path}`; exact match first, else the first `old + "/"` prefix |
| `session-folders.json` | `{session id: request folder}`; used when a session's cwd carries no metadata |
| `no-audit.txt` | one session id per line; `#` comments |
| `activity/YYYY-MM-DD.json` | `[events]` or `{"events": [...], "subjects": {session id: subject}}`; event: `source` (`meeting` `email` `chat` `personal` `leave` `notice`), `start` (required, local ISO), `end`, `title`, `counterparties`, `detail`, `ref`, `subject`. `claude-audit --schema` prints the contract |
| `review/ledger.json` | §6.6 |
| `review/jira.json` | `[{key, summary, status, updated, mine}]` |
| `review/proposals_<monday>.json`, `review/decisions_<monday>.json` | §6.7 |
| `claude-audit_<label>_<view>.csv` (+ `_breakdown.csv`) | §6.2 |
| `quality/<from>_<to>_retro.md`, `quality/history.json`, `quality/judged.json` | §10 |
| `guard/judge.jsonl`, `guard/reviews.jsonl` | [guard LLD §10a](guard/lld.md#10a-judge-journal-and-review) |

### 5.3 Transcript fields used

From Claude Code's `<id>.jsonl` (one JSON object per line): `timestamp`, `promptId`, `type`
(`user`, `assistant`, `ai-title` → `aiTitle`, `last-prompt` → `lastPrompt`, `cost-state` →
`totalCostUSD`, `totalLinesAdded`, `totalLinesRemoved`, `modelUsage`), `cwd`, `gitBranch`,
`version`, `isSidechain`, `isMeta`, `message.content` (text blocks, `tool_use` inputs,
`tool_result`). Files named `agent-*` (sub-agent logs) are skipped.

---

## 6. claude-audit

### 6.1 CLI

**Period** (`resolve_period`; default the current Monday–Sunday week):
`--day [DATE]`, `--week [DATE]`, `--month [YYYY-MM]` (summary uses the weeks that start in the
month), `--from DATE [--to DATE]` (`--to` defaults to today). Dates: `YYYY-MM-DD` or `today`.
Conflicting or malformed periods exit 1.

**Views**, first match wins: `--propose` > `--by-type` > `--sessions` > `--reconcile` > `--detail` >
summary. `--detail` with `--reconcile` is rejected.

**Output:** `--copy` (TSV to the clipboard: summary uses the tracker's columns with no header;
other views include a header), `--csv [FILE]` (default
`<root>/_audit/claude-audit_<label>_<view>.csv`; `-` = stdout with messages on stderr; the summary
also writes `<name>_breakdown.csv`).

**Advanced** (`--help-all`): `--apply FILE`, `--ledger PATH`, `--activity PATH`, `--schema`,
`--busy-cap MIN` (5), `--read-cap MIN` (2), `--round-to MIN` (30), `--min-subject MIN` (10),
`--util-step PCT` (10), `--with-type`, `--no-type`.

Every run lists weekdays up to today with no activity file.

### 6.2 Output columns

| View | Columns |
|---|---|
| summary | the tracker's 14 headers (`REVIEW_COLUMNS`, including its own spelling "Refernce Architectures"), first header `Day` or `Week`, + `Task Type` unless `--no-type` |
| breakdown | row_id, week, task, ticket, utilization, hours (rounded up to 0.5 h), hours_exact, sessions, meetings, emails, chats, confirmed, declared, auto_mapped, inferred, standalone, flags_from, jira_status, flag_evidence, comments_from, task_types, subject_ids, subjects |
| `--detail` | date, weekday, start, end, source, task, ticket, task_type, title, subject, duration, duration_exact, worked, scheduled, counterparties, detail, cost_usd, event_id, subject_id, session_id, row_id |
| `--sessions` | date, weekday, start, end, worked_h, worked_exact, elapsed, ticket, task_type, title, folder, git_branch, turns, cost_usd, lines_added, lines_removed, models, last_prompt, session_id, cli_version |
| `--by-type` | task_type, sessions, hours, hours_exact, share, tickets, titles |
| `--reconcile` | side, status, ticket, task, summary, jira_status, updated, hours, activities, note |

### 6.3 Transcripts → session rows (`gather`)

1. `transcript_files()` — `*.jsonl` under each `CLAUDE_HOMES` dir's `projects` (links followed,
   `agent-*` skipped; a projects dir reached twice is walked once, a real path read once, and a
   session id already found in an earlier home skipped). Ids in `no-audit.txt` are skipped.
2. `read_session` — timestamps (tz-aware, sorted), turn starts (earliest timestamp per
   `promptId`), last `cost-state`, `aiTitle`, `lastPrompt`, the opening prompt and up to 40 prompts
   × 400 chars (for matching), first `cwd`/`gitBranch`/`version`; `cwd` through `moved_path`.
3. `session_meta(cwd)` — skips `audit: false`. `meta_for` falls back to `session-folders.json` when
   the cwd has no metadata.
4. `split_by_day` — local calendar days; cost booked to the last day. `build_row` per day; kept when
   its start is in the period.
5. Activity events are loaded and kept when they overlap the period.
6. `prepare_items` (§6.5) and an IDF table over item tokens.

**Worked time** (`worked_seconds`): within a turn, each gap counts up to `busy_cap` (300 s); from a
turn's last event to the next turn's start, up to `read_cap` (120 s); the last turn gets no reading
credit; fewer than two events = 0. `worked_h` is rounded up to `--round-to`.

**Attribution:** ticket and type only from `.session.json`; `task_type` =
`session_types[id]` else the folder's; a declared `Other` ticket = none; declared tickets in
`ignore_tickets` are dropped.

### 6.4 Subject time (`subject_seconds`)

Session worked time counts in full. A meeting adds its booked time only if no same-subject
session's start–end overlaps it. A subject made only of emails and chats counts each item's span
plus gaps capped at `read_cap`; otherwise emails and chats add nothing. `leave`, `personal` and
`notice` are excluded.

### 6.5 Subjects and tracker rows

**Subject assignment** (`prepare_items`): `_lkey` = session id, or `stable_id("evt_", source, start,
title)`. Precedence: ledger `assign[_lkey]` (confirmed) → the event's `subject` or the activity
file's `subjects` map (inferred) → `clean_title` (standalone; strips Re:/Fw:/Accepted: prefixes).
Jira keys (`[A-Z][A-Z0-9]{1,9}-\d{1,6}`, minus `JIRA_DENY`, restricted to `jira_prefixes` when set)
come from titles, text and folders.

**Rows** (`build_review`, per week):

1. Group items by subject. Mapping = `ledger.subjects[sub_id]`; else a single declared ticket of a
   registered task (`declared`). A subject under `--min-subject` and unmapped is *minor*.
2. `auto_map_small` maps minor subjects to the best `candidate_tasks` match (≥ 0.3) or
   `default_task` (`auto`).
3. Group by `(task, ticket)`; `(ignore)` dropped; unmapped → `(unmapped)`; ticket `Other` → the
   task's `default_ticket`.
4. Leave: workdays 09:00–17:00 covered, rounded to half days; a week override wins;
   `leave_pct` = leave/workdays × 100, rounded to the step.
5. Utilisation: overrides kept; `100 − leave − fixed` split by largest remainder (`allocate`),
   every row with time gets at least one step; step halves (10→5→2→1) when rows ≥ steps.
6. Flags: substring hints (`FLAG_HINTS`) on titles, folders and details, rituals skipped, lines
   added > 0 → Development; overrides merged. Comments: week override → task `comments[ticket]` →
   subject names by time (160 chars). Meetings & Interactions = Yes when any meeting/mail/chat.
7. `(unmapped)` appears in the breakdown, never pasted; a Leave row when `leave_pct` > 0.
8. Row task type = the heaviest type by worked seconds.

**Detail** (`activity_view`) re-derives per bucket (by start); `duration` on each subject's first
row. `reconcile()` sums `duration_exact` per `row_id` against the breakdown's `hours_exact`
(tolerance 1 s).

**Reconcile** (`reconcile_view`): activities → tickets (`ok`, or `x` when unmapped); tickets → Jira
issues that are `mine`, not ignored and updated in the window: `ok` (booked), `?` (a look-alike by
token overlap ≥ 0.3, key mention, or shared words while active ±15 min), `x` (nothing).

### 6.6 Ledger (`_audit/review/ledger.json`)

```
{version:1, leave_task:"Leave", default_task:"", jira_prefixes:[], ignore_tickets:[],
 tasks:[{task, tickets[], default_ticket?, keywords[]?, paths[]?, comments{ticket:text}?, flags?}],
 assign:{item_key:{subject, status, at}}, reject:[[k1,k2]],
 subjects:{sub_<sha>:{subject, task, ticket, status, at}},
 weeks:{monday:{leave_days?, rows:{"task|ticket":{comments?, flags?, utilization?, meetings?}}}}}
```

Saved atomically with sorted keys. A corrupt ledger exits 1 (it's loaded by every view).

### 6.7 Propose and apply

**`--propose`** (one week) writes `proposals_<monday>.json`: `links[]` (session ↔ meeting/mail/chat
within 36 h, sessions with ≥ 120 s worked; `score_link`: shared Jira key +0.6, same inferred subject
+0.35, 0.5 × weighted word overlap, meeting timing +0.25/+0.2/+0.15, mail ±15 min +0.15 or ±60 min
+0.1, chat ±10 min +0.15, capped at 1; tiers *likely* ≥ 0.6, *possible* ≥ 0.3) and `tasks[]`
(`candidate_tasks`: ticket in task +0.7, Jira summary +0.5 × similarity, folder path +0.35,
keywords up to +0.5; top 3). `weighted_overlap` uses IDF = log(1 + n/df) and ignores tokens in more
than 25 % of items.

**`--apply FILE`** merges: `assign` (confirmed), `reject` pairs, `remove_tasks`, `ignore_tickets`,
`tasks` (lists unioned, dicts updated, null deletes, scalars replaced), `subjects` (creates tasks,
adds tickets), `weeks` (rows merged per key; null clears), `jira_prefixes`, `leave_task`,
`default_task`. With no other view flag it stops after the merge.

### 6.8 Constants

busy cap 5 min · read cap 2 min · round-to 30 min · min-subject 10 min · util step 10 % · link
tiers 0.6/0.3 · link window 36 h · breakdown hours always rounded to 30 min · 40 prompts × 400
chars kept · comment 160 chars (48 on screen) · local time zone throughout.

---

## 7. claude-sessions

**CLI:** `claude-sessions [N]` (default 30), `-a/--all`, `--json`. Text: one line per session
(`YYYY-MM-DD HH:MM  <id>  <cwd>  <first prompt>`) and a resume hint.

**Rows** (`sessions()`): one per session id, most recent transcript copy wins; `cwd` from the head
through `moved_path` (else the project folder name); sorted newest first.

**Request folder** (`request_dir`): nearest `.session.json` above cwd within the root → the
`YYYY/MM/DD/<name>` folder containing cwd → `session-folders.json` → none.

**JSON** (`as_json`), consumed by the sidebar:

```
{ work_root,
  sessions: [{ id, mtime, cwd, in_work_root, title, last_prompt, first_prompt|null, started|null,
               written:[abs], request: null | {path, name, started, ticket, task_type,
               files:[rel], files_truncated}, audited, artifacts:[abs],
               deletable:{ok, why:[], blocked:[]} }],
  requests: [{ path, name, started, ticket, task_type, files, files_truncated, mtime }] }
```

- `title`/`last_prompt` from the transcript's tail (last 512 KiB; whole file if either is missing);
  `started` from the first timestamp in the first 200 lines.
- `files` (`folder_files`): sorted walk, hidden names and `node_modules __pycache__ venv .venv .git`
  skipped, capped at 500 (`files_truncated`).
- `written` (`written_files`): Write/Edit/MultiEdit `file_path` and NotebookEdit `notebook_path`,
  parsed incrementally from a cached byte offset (`<CWS_CACHE_DIR|XDG_CACHE_HOME|~/.cache>/
  claude-worksessions/written.json`), then mapped through moves and filtered to existing files
  outside `~/.claude*`.
- `requests` (`idle_requests`): folders matching `YYYY/MM/DD/*/.session.json` that no listed session
  with a prompt belongs to; `mtime` = newest of the metadata and its files.

**Value check** (`value_check`, used by `claude-delete` and the sidebar):
- `audited` = the folder's `audit` flag and not in `no-audit.txt`;
- `artifacts` = existing written files + the request's files when it's the request's only session;
- `why` (grounds): `no artifacts`, `kept out of the review (-n)`;
- `blocked`: `booked in the weekly review` (id found in the ledger text), `open in a running Claude
  session` (`<cfg>/sessions/*.json` with a live pid, or a UUID on a `claude` command line from
  `ps`), `active in the last two minutes`, `it has artifacts and counts in the review`;
- `ok` = grounds and no blocks.

---

## 8. claude-search

**CLI:** `claude-search QUERY… [--from DATE] [--to DATE] [--limit N (10)] [--all] [--ai]
[--no-pick] [--csv [FILE]]`.

**Index** (`build_index`), `~/.claude-session/cache/search-index.json`, version 2: per transcript
`{stamp: [mtime, size], doc}`; re-extracted only when the stamp changes. `doc`: `session_id`, `cwd`,
`title`, `start`, `end`, `worked` (300/120 caps), `tf` (per-field stem counts), `keys` (per-field
ticket keys), `snip` (prompts ≤ 20 000, assistant ≤ 30 000 chars). Fields: title (`ai-title` or the
opening prompt), prompts, assistant, tools (`tool_use` inputs and `tool_result`s, 1 500 chars each,
200 000 total), folder (last two path parts), linked (activity assigned to the same subject).

**Terms:** lowercase alphanumerics, numbers dropped, `SYNONYMS`, stop words and short words
removed (except `KEEP_SHORT`), stemmed with `claude-audit`'s `_stem`. **Ticket keys:**
`\b([A-Za-z][A-Za-z0-9]{1,9})-(\d{1,6})\b`, uppercased, minus `JIRA_DENY`.

**Ranking** (`search`):

1. Each word → a concept: its stem (1.0) plus `EXPAND` words (0.5); a ticket key's Jira summary
   adds its stems at 0.35.
2. BM25 per field (k1 1.2, b 0.75), field weights title 6, prompts 3, linked 2, folder 2,
   assistant 1, tools 0.5; expansion words ignored in tools.
3. Phrase in title or prompts +6.
4. Ticket evidence: declared +12, booked in the ledger +10, mentioned in title/prompts/folder +8
   (tier 2), else in assistant/tools/linked +2 (tier 1).
5. Order: tier (ticket searches), score, start. Levels: ticket searches *on ticket* / *mentioned* /
   *related*; word searches *strong* (≥ 0.5 × top), *likely* (≥ 0.2), *possible*.
6. Without `--all`, *possible* is dropped; ticket searches show every *on ticket*, up to 3
   *mentioned* and 3 *related*.

**`--ai`** (`ai_rank`): the top 20 as JSON lines → `claude -p --no-session-persistence --model
haiku` (stdin, cwd temp dir, 240 s); keeps Claude's picks with its reason; on failure keeps the
local ranking.

**Output:** header, per result rank/level/time span/worked/task·ticket/title/why/snippet (220 chars)
and `cd <folder> && [CLAUDE_CONFIG_DIR=<home>] claude --resume <id>`: the home its transcript is in
(`home_of`), named only when it isn't what a bare `claude` uses (`resume_config_dir`). On a
terminal (no `--no-pick`) it offers to resume one (`os.execvp("claude", …)` with that
`CLAUDE_CONFIG_DIR`), or, when `CWS_OPEN_CMD` opens in T3 (or `--t3`), opens its T3 thread. CSV columns:
rank, level, score, session_id, start, end, worked, task, ticket, title, folder, why, snippet,
resume.

---

## 9. claude-delete

**CLI:** `claude-delete ID [--yes] [--check] [--json]`, `--list [--json]`, `--restore ID`,
`--purge ID`, `--empty`. `ID` is a unique prefix (`find`).

**Flow:** header → if `deletable.ok` is false, "Can't delete it: …", exit 1 → "It may go: …" and
`impact()` (can't be resumed or found; review impact; produced files stay, up to 6 listed; the
request folder goes when empty; restorable) → `--check` stops → confirm (`y`/`yes`; no TTY without
`--yes` refuses) → `delete()`.

**`delete()`** moves `leftovers(sid)` from every Claude config dir — `projects/*/<sid>.jsonl`,
`projects/*/<sid>/`, `file-history/<sid>`, `session-env/<sid>` (de-duplicated by real path) — plus
the request folder when `empty_request` (no visible files, only session, strictly inside the root),
then removes the session's pin. Files the session wrote are never touched.

**Bin** (`CWS_TRASH_DIR`, else `$XDG_DATA_HOME|~/.local/share/claude-worksessions/trash`):

```
<bin>/<YYYYmmdd-HHMMSS>_<id8>[-<hex4>]/manifest.json
<bin>/.../items/<i>_<basename>
manifest: {id, title, request, request_path, ticket, last_activity, deleted_at,
           items:[{from, name}]}
```

`restore` refuses (moves nothing) if any original path exists, else moves every item back and
removes the bin folder. `--purge`/`--empty` delete for good after confirmation.

---

## 10. claude-retro

**CLI:** `--days N` (7) | `--week [DATE]` (last week), `--no-judge`, `--model` (sonnet), `--out`.

**Collection:** sessions from `claude-sessions` whose start or mtime falls in the period and that
have a real prompt (not `<…`, `[Request interrupted`, `Caveat:`).

**Signals** (`scan`, sidechain/meta records skipped), each tied to the prompt before it:

| Signal | Rule |
|---|---|
| clarifying question | an `AskUserQuestion` call, or the last assistant text before the next prompt ends in a question that matches `ASKS` and not `OFFER` |
| rejected tool call | a tool result containing "doesn't want to proceed" |
| missing data or resource | `MISSING` in the first 3 000 chars of an error or short result |
| interrupted | text starting "[Request interrupted" |
| correction | prompt starting no/nope/that's not/wrong/i meant/not what i/actually i/you misunderstood/that isn't |
| reversal | undo/revert/roll back/revoke/abandon/scrap that/forget it in the first 200 chars (not a correction) |

`collapse` merges per (signal, prompt).

**Judging:** sessions with episodes and no cached verdict, 5 in parallel, `claude -p --model <model>
--no-session-persistence`, prompt on stdin (episodes ≤ 24 000 chars), 600 s, 2 attempts. Verdicts:
`prompt_caused`, confidence, cause (`assumed-exists`, `ambiguous-target`, `conflicting-instructions`,
`missing-acceptance`, `scope-change`, `claude-error`, `normal`), a better prompt. Cached in
`judged.json` by a hash of the session's episodes; errors are retried next run.

**Report** `<root>/_audit/quality/<from>_<to>_retro.md`: summary, signal table, causes, habits to
keep (top 8), worst episodes (top 6), failures, trend (last 8 periods). `history.json` keeps one
entry per period (replaced on re-run; only when judged). Only high- and medium-confidence
prompt-caused verdicts count; `per_100_prompts` = caused / prompts × 100.

---

## 11. Hooks and claude-guard

All hooks read the hook payload on stdin, write JSON or nothing, and exit 0 (fail open).

### 11.1 `claude-hook-vague` (`UserPromptSubmit`)

Counts prompts per session in `<tmp>/claude-hook-vague-<id>.count` and only speaks on the first two.
Vague = 3–40 words, matches `ACTION` (check, fix, investigate, create, update, delete, grant, …),
not a confirmation or slash command, and no `ANCHOR` (quote, backtick, path, URL, ticket, dotted,
snake_case or dashed name, environment word, file extension, 3+ digit number). Output:
`additionalContext` asking Claude to ask one or two questions unless the context already answers them.

### 11.2 `claude-hook-notfound` (`PostToolUse`, `PostToolUseFailure`; `Bash|mcp__.*`)

Scans the tool response (for a Bash call, only `stderr`), `error` and `tool_output` for
`TABLE_OR_VIEW_NOT_FOUND`, `SCHEMA_NOT_FOUND`, `CATALOG_NOT_FOUND`, `VOLUME_NOT_FOUND`,
`FUNCTION_NOT_FOUND`, `PRINCIPAL_DOES_NOT_EXIST`, `RESOURCE_DOES_NOT_EXIST`, `ResourceNotFound`,
`ResourceGroupNotFound`, `ContainerNotFound`, `BlobNotFound`, `PathNotFound`, `\bdoes not exist\b`.
At most 3 per session (`<tmp>/claude-hook-notfound-<id>.count`). Quotes the error line (≤ 160 chars)
in `additionalContext`: confirm the name and environment with the user before hunting for
alternatives.

### 11.3 `claude-guard` (`UserPromptSubmit`, `PreToolUse`, `Stop`)

Scope, pivot and loop checks with an isolated judge, shadow and enforce modes, a per-folder log and
a central journal. Fully specified in the [claude-guard LLD](guard/lld.md).

---

## 12. Output utilities

### 12.1 `claude-md-email`

`claude-md-email FILE [--open | --html OUT]`. `pandoc FILE -f gfm -t html5` (a fragment); the CSS
at `<repo>/yazi/md-email.css` is parsed (simple tag selectors only) and inlined onto every element
(Outlook drops `<style>` on paste), wrapped in a `<div>` with the body rule minus margin and
max-width. Clipboard: macOS via JXA (`NSPasteboardTypeHTML` + the Markdown as plain text); WSL via
`powershell.exe Set-Clipboard -AsHtml`; Linux via `wl-copy --type text/html` or `xclip -t text/html`.
`--open` writes a full page to `<tmp>/md-email/<stem>.html` and opens it; `--html -` writes the
fragment to stdout.

Stylesheet: Calibri/Arial 11pt black; h1–h3 16/14/12pt; tables collapsed, 1px #999 borders, header
background #e8eef7; code Consolas 10pt on #f3f3f3.

### 12.2 yazi

`yazi.toml` (rendered) adds a Markdown preview with glow (via the `piper` plugin), `Enter` on `.md`
→ `md2html.sh` (`pandoc -s` with `md-email.css` as a `<style>` block, opened in the browser), and
Glow / Glow (light) openers.

---

## 13. VS Code extension (`vscode/`)

### 13.1 Manifest

`jviegas6.claude-worksessions`, `engines.vscode ^1.93.0`, activation `onStartupFinished`. One
activity-bar container `claudeWorksessions` (icon `history`) with a webview `claudeWorksessions.search`
and a tree `claudeWorksessions.sessions`.

### 13.2 Data and refresh

`loadData()` runs `<sessionsCommand> -a --json` (`execFile`, 64 MB buffer). `sessionsCommand` is the
`claudeWorksessions.sessionsCommand` setting or `~/.local/bin/claude-sessions`; sibling tools
(`claude-search`, `claude-delete`, `claude-md-email`) are resolved from the same folder. `refresh()`
coalesces concurrent calls, reloads pins, relinks tabs and re-renders.

Triggers: the Refresh command; setting changes; file watchers (debounced 1 500 ms) on
each `CWS_CLAUDE_HOMES` dir's `projects/**/*.jsonl` (real paths, deduplicated) and `<work root>/[0-9]*/*/*/*/**`; a bin watcher on
`*/manifest.json` (re-render only); a pins watcher on `_config/pinned.json` (reload pins); after
set-type, delete, restore, purge.

### 13.3 State

`globalState`: `grouping` (`day`), `sort` (`activity`), `filters`
(`{day:{preset:"any"}, tickets:[], artifacts:"any"}`). `workspaceState`: `tabs`
(`{terminal name: session id}`, relinked by name after reload). In memory: the search text,
pins, pending tabs (new requests and new sessions waiting for their transcript), desired tab
names. Context keys `claudeWorksessions.filtered` / `filtering` drive the toolbar icons.

### 13.4 Tree model (`model.js`)

- **Visibility** (`visible`): in the work root or with a request; non-empty unless
  `showEmptySessions`; matches the search; passes the filters.
- **Requests** (`requests`): visible sessions grouped by request path (sessions without one share
  a "Work root" pseudo-request); plus session-less `requests` from the JSON that match and pass
  (tested as pseudo-sessions whose files are their artifacts). `mtime` = newest session, `started`
  = request start → oldest session → `mtime`.
- **Groupings**: `day` (by the `YYYY/MM/DD` path; days always newest first; `(work root)` and
  `(elsewhere)` last), `ticket` (`(no ticket)`), `recent` (flat sessions). A **Pinned** group comes
  first when anything pinned is visible, then an **Active** group (`active`) of the visible
  sessions `claude-sessions` marks `active` (a live Claude process has them open).
- **Sorts**: `activity` (mtime), `started`, `name` (locale, numeric).
- **Search** (`matches`): every word must appear in the session's title, prompts, id, or its
  request's name, ticket, type, path or file names.
- **Files** (`shownFiles`): narrowed only by words that match nothing but file names; the label
  shows `shown of total` when narrowed, and the size (`request.size`, or the sum of the listed
  files when narrowed). `fileChildren` builds one folder level at a time.
- **Filters** (`passes`): day presets (today, yesterday, last 7 days, this/last week, this month, a
  date; a session is on a day it was active), tickets (including `(no ticket)`), artifacts
  (with/without).
- **Pins**: `<work root>/_config/pinned.json`, `{sessions:{id:t}, requests:{relpath:t}}`.
- **Deleted**: the bin's manifests matching the search; hidden while filters are on.

Node kinds: `pinned`, `group`, `request`, `session`, `files`, `dir`, `file`, `deleted`,
`deletedSession`. Item ids embed the grouping and search text so expansion state resets when they
change.

### 13.5 Commands

| Command | Action |
|---|---|
| New request | pending tab running `claude-new` in the work root |
| Open (session click) | focus its tab, else `[CLAUDE_CONFIG_DIR=<config_dir>] claude-resume --resume <id>` in its cwd (`config_dir` from `claude-sessions`) |
| New session in this request | pending tab running `claude` in the folder (the terminal's login) |
| Search… / with Claude… | `claude-search <q> --csv - --no-pick --limit 25 [--ai]` → quick pick |
| Audit… | period and view → `claude-audit …` in a terminal |
| Recent sessions… | quick pick of visible sessions |
| Set task type… | writes `.session.json` directly (`M.setTaskType`) for a request or a session |
| Go to request… | open in a new window, reveal, or new session |
| Run skill… | skills from each `CWS_CLAUDE_HOMES` dir's `skills`; `claude-new --prompt '/<skill>' '<name>'` |
| Resume session by id… | `claude-resume --resume <id>` |
| Filter… / Clear filters / Sort… / Change grouping / Refresh / Clear search / Focus search | view state |
| Pin / Unpin | toggle in `pinned.json` |
| Reveal / Reveal in Finder / Open in a new window / Copy session id / Copy path / Open file | as named; Markdown opens in the preview |
| Copy for email | `claude-md-email <file>` (from the sidebar, editor, preview or Explorer; saves first) |
| Delete session… | `claude-delete <id> --json` → modal with the impact → `--yes`; closes the tab |
| Restore / Delete for good… / Empty the bin… | `claude-delete --restore / --purge --yes / --empty --yes` |

Terminals open in the editor area, named `TICKET · title` once the session is known.

### 13.6 Search box (webview)

One input with a strict CSP. Typing filters the tree; Enter runs Search; Escape clears. The text is
kept in the webview state and re-applied on reload. The hint shows `<shown> of <total> sessions`.

### 13.7 Packaging

`package_vsix.py OUT.vsix` zips `[Content_Types].xml`, `extension.vsixmanifest` and
`extension/{package.json, extension.js, model.js}` with the version taken from `VERSION` (the repo's
`package.json` says `0.0.0`). `install.sh` installs it with `code --install-extension --force` when the
installed version differs.

### 13.8 Settings

`claudeWorksessions.sessionsCommand` (empty = `~/.local/bin/claude-sessions`),
`claudeWorksessions.showEmptySessions` (false).

---

## 14. Skills

None ship with this package since 3.0.0; install them separately (e.g. with Skillshare). Their
contract with the commands:

- **Day files**: `_audit/activity/YYYY-MM-DD.json` in the schema `claude-audit --schema` prints,
  times already local, events carrying `subject`, calendar entries classed `leave` / `personal` /
  `notice`. A skill writes them from Microsoft 365; the commands never call the connectors (D7).
- **Review**: `claude-audit --week D --propose`, `--apply` on a decisions file, `--reconcile`, and
  `--report` for the weekly email; the ledger changes only through `--apply`.
- **Settings**: skills read `~/.config/claude-worksessions/config.env` at run time.

---

## 15. Known limitations

From reading the code; each is a candidate for an issue.

**Configuration and shell**

1. The zsh loader lets the config file overwrite environment variables, while the Python loader
   lets `CWS_*` environment variables win; `docs/configuration.md` describes only the latter.
2. A value containing `"` is written escaped by the installer (`cws_set`) but cut at the first quote
   by the loaders.
3. `ws`: the fzf preview uses the work root unquoted, which breaks on paths with spaces (e.g. a WSL
   `OneDrive - <org>` path); with no request folders the glob errors.
4. `claude-type` identifies "this session" as the folder's most recently modified transcript; two
   concurrent sessions in one folder can be mislabelled.
5. `ended_at` is never written: nothing waits for the app `CWS_OPEN_CMD` opens.
6. Stale references: `folder-layout.md` and `context.example.md` say `CLAUDE.md` imports
   `context.md` (it inlines it).
7. `--no-brew` doesn't stop the Command Line Tools, Homebrew or Claude Code installs; `--yes` on a
   first run leaves the example `CWS_CLAUDE_HOMES`.
8. Rendered files (`CLAUDE.md`, skills, yazi) lag the repo until `install.sh` runs.

**claude-audit**

9. Which Claude login ran a session isn't recorded; resume lines take the home its transcript is in.
10. `audit: false` is checked on the cwd only, not on a folder assigned via `session-folders.json`.
11. `moved_path` takes the first matching prefix in file order, not the longest.
12. `(unmapped)` rows take a share of utilisation but aren't pasted, so pasted percentages can sum
    below 100 (a note says so).
13. Flag inference is plain substring matching ("fix" in "prefix").
14. A meeting is dropped when a same-subject session's span overlaps it, even if the session was
    idle.
15. No caching: every run re-reads every transcript. `--schema` text mentions a subjects CSV that
    isn't produced.

**Other commands**

16. `claude-sessions`: "booked in the review" is a substring search of the ledger text;
    `running_sessions` accepts any UUID on a `claude` command line.
17. `claude-search`: three `EXPAND` keys can never match (they're looked up by stem: "firewall" →
    "fw", "access" → "acces", "billing" → "bill"); snippets miss synonym-mapped words (an xfail
    test); a lowercase `word-123` in a query counts as a ticket; the index path ignores
    `CWS_CACHE_DIR`.
18. `claude-delete`: an "empty" request folder can still hold hidden files, which move with it;
    restore isn't transactional if a move fails midway.
19. `claude-retro`: `ASKS` includes "or", so most trailing questions with "or" count.
20. `claude-md-email`: a self-closing tag with no CSS rule is rewritten with a doubled slash
    (`<br />` → `<br //>`); only simple tag selectors are supported.
21. `claude-new` runs `CWS_OPEN_CMD` / `CWS_AFTER_NEW_CMD` with `eval`: the templates are your
    own config, trusted like a shell alias.
22. Hooks: counter files in the temp dir are never cleaned; `claude-hook-vague` counts confirmations
    and slash commands towards its two prompts; `does not exist` in a non-Bash tool's normal output
    still triggers `claude-hook-notfound`.

**VS Code extension**

23. Watchers are bound to the configured work root and Claude config dirs at activation.
24. Tabs are renamed only when active; relinking after reload is by terminal name.
25. Set task type writes `.session.json` itself (not atomic, no trailing newline) instead of calling
    `claude-type`.
26. "Last week" and the date prompts default from UTC dates while day filters use local time.
27. The Recent grouping and the hint counts leave out session-less requests; the Deleted group hides
    under filters.
28. The packager ships a fixed list of files; a new source file must be added to it.

claude-guard's own limitations: [guard LLD §20](guard/lld.md#20-known-limitations).

---

## 16. CI, release and tests

**`tests.yml`** (pull requests and pushes to `main`):

- `test`: Ubuntu and macOS, Python 3.12, zsh on Linux, `pytest`. `pyproject.toml` measures
  coverage of `bin/*` and `vscode/*.py` and fails under 95 %. Shell code is tested by running it
  (`zsh -fc`) against a temporary HOME with stubs; the extension by `node --test` against a fake
  `vscode` module.
- `install-linux`: a real `install.sh --yes` on a clean Ubuntu (Homebrew removed so apt is used),
  then in a login zsh: `claude-new -L`, `claude-resume -h`, the Python commands' `--help`, `fzf
  pandoc claude` on PATH, the `.zshrc` block and `CLAUDE.md` present; re-run must print
  "block up to date".

**`release.yml`** (push to `main` touching `VERSION`): reads `VERSION`; if the tag exists, stops;
extracts the `## [<version>]` section of `CHANGELOG.md` (fails if empty); creates an annotated tag
`v<version>` and a GitHub release marked Latest.

**Process** (`docs/releasing.md`): semver (major = the upgrade needs user action; minor = features;
patch = fixes); every change through a pull request; bump `VERSION` and add the changelog section on
the branch; merging releases.

**Tests** (≈ 330 pytest + ≈ 37 node):

| File | Covers |
|---|---|
| `test_audit_core.py`, `test_audit_report.py` | config, transcripts, attribution, worked time, activity, ledger, subjects, links, tasks, every view, CSV, clipboard, propose/apply, reconcile |
| `test_sessions.py` | rows, moves, tail reading, request folders, JSON, files, written-files cache, idle requests |
| `test_search.py` | terms, keys, extraction, index cache, booking, ranking levels, ticket tiers, `--ai`, CSV, resume |
| `test_delete.py` | value check, running sessions, find, impact, leftovers, bin round trip, restore refusal, CLI |
| `test_quality.py` | hooks, `claude-retro` signals, judging, report, history |
| `test_guard.py` | [guard LLD §18](guard/lld.md#18-tests) |
| `test_md_email.py` | CSS parsing, inlining, rendering, clipboard per OS |
| `test_shell.py` | `claude-new` (open/after-new templates, removed options), `claude-resume`, `claude-type`, `claude-goal`, install and uninstall (hooks, old wrapper, extension, Claude config dirs) |
| `test_vscode.py` + `vscode/test/*.js` | the extension model and UI, packaging |
| `test_smoke.py` | the Python scripts load as modules |
