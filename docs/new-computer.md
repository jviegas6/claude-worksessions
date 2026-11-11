# Moving to a new computer

What lives where decides what you need to carry:

| what | where | on the new machine |
|---|---|---|
| this package (the commands) | GitHub | `git clone`; `install.sh` |
| your skills | wherever you keep them (e.g. a Skillshare source) | install them as that tool says |
| your config, context, review rules | `<work root>/_config/` | arrives with the synced work root |
| request folders, `_audit/` (ledger, activity) | `<work root>/` | arrives with the synced work root |
| Claude history (transcripts) | `<dir>/projects/` for each `CWS_CLAUDE_HOMES` dir | **copy it** — the audit and search are built from it |
| logins, gateway token | each Claude config dir's `.claude.json`, `settings.json` | sign in again in the app that runs Claude (T3 Code's providers, an IDE) |

## Steps

1. Sign in to OneDrive (or whatever syncs the work root) and let it finish syncing —
   **same path as before** if you can, so folder paths in old transcripts still resolve.
   Command Line Tools, Homebrew, Claude Code and the packages are installed by
   `install.sh` in step 3; nothing to do by hand. On Linux or WSL install `zsh` and
   `git` first (see the README).
2. Copy the history from the old machine:
   ```sh
   rsync -a old-mac:~/.claude-personal/projects/ ~/.claude-personal/projects/
   ```
   (`history.jsonl` and `file-history/` too, if you want prompt history and undo data.)
3. Clone and install, pointing at the synced config:
   ```sh
   git clone https://github.com/jviegas6/claude-worksessions.git ~/Repos/claude-worksessions
   cd ~/Repos/claude-worksessions
   ./install.sh --config "<work root>/_config/config.env"
   ```
4. Sign in to Claude in the app you use (in T3 Code: *Settings > Providers*, one config dir per
   login, the same dirs as `CWS_CLAUDE_HOMES`). Your claude.ai connectors come back with the
   login; re-add any local MCP servers you use.
5. Check: `claude-new -l`, `claude-audit --week`, `claude-search <something you know>`.

Moving between a Mac and Linux/WSL always changes the path (`~/Library/CloudStorage/…`
becomes `/mnt/c/Users/…/OneDrive - …`), so the next paragraph applies.

If the work root ends up at a **different path** (e.g. a different OneDrive tenant
name), set `CWS_WORK_ROOT` in `config.env` and record old → new in
`_audit/moved-folders.json` for the folders you care about (see
[folder-layout.md](folder-layout.md)); without it the audit loses the ticket and type
for those sessions.
