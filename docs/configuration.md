# Configuration

## Where the config is read from

1. `$CWS_CONFIG`, if set
2. `~/.config/claude-worksessions/config.env` — `install.sh` makes this a symlink to
   `<work root>/_config/config.env`

The zsh functions, `claude-audit`, `claude-search` and `install.sh` all read the same
file. Environment variables named `CWS_*` override it.

Format: `KEY="value"` lines, `#` comments, `$HOME` expanded. Nothing else is
interpreted — it is not executed as shell.

You don't have to write it by hand: the first `install.sh` asks for everything, and
`install.sh --profiles` re-asks the profile questions. Editing the file directly works
just as well — re-run `install.sh` afterwards so the skills and `CLAUDE.md` catch up.

## config.env

| key | default | used for |
|---|---|---|
| `CWS_WORK_ROOT` | `$HOME/work_sessions` | where request folders, `_audit/`, `_config/`, `_daily/` live |
| `CWS_ORG` | — | skills' wording; also ignored as a matching word in the audit |
| `CWS_USER_ROLE` | — | skills' wording ("a data/platform engineer at …") |
| `CWS_TIMEZONE` | `UTC` | IANA zone the recap normalises to |
| `CWS_TIMEZONE_WINDOWS` | `UTC` | the same zone as Outlook names it (e.g. `GMT Standard Time`) |
| `CWS_TICKET_EXAMPLE` | `PROJ-123` | prompts and help text; any `PREFIX-123` or `Other` is accepted |
| `CWS_JIRA_CLOUD_ID` | — | the weekly review's Jira query (Atlassian MCP `getAccessibleAtlassianResources` gives it) |
| `CWS_PROFILES` | `personal work` | Claude profiles; each is `~/.claude-<name>`, picked with `-p <name>` in `claude-new` / `claude-resume` |
| `CWS_DEFAULT_PROFILE` | first profile | what a bare `claude` uses; the default in `claude-new`'s menu |
| `CWS_SHARED_PROFILE` | first profile | the profile that owns history, projects, skills, plugins, MCP |
| `CWS_PROFILE_<name>_DESC` | — | the line shown in `claude-new`'s profile menu |
| `CWS_PROFILE_<name>_BASE_URL` | — | route that profile through an API gateway (see below) |
| `CWS_TASK_TYPES` | permissions, job errors, … | seed list of task types; the ones you have used are suggested first |
| `CWS_INSTALL_YAZI` | `1` | install yazi, glow, pandoc and the Markdown extras |

Changing a value: edit the file, open a new terminal. Re-run `install.sh` when you
changed the work root, org, role, time zone, ticket example, Jira id or profiles —
those are rendered into the skills and the work root's `CLAUDE.md`.

## Profiles

Have as many as you like. Names are lowercase letters, digits and underscores — no
dashes, because the name becomes part of `CWS_PROFILE_<name>_DESC` / `_BASE_URL`.
Each is either a **Claude subscription** — you sign in with
your account, and `install.sh` offers to open it for you — or an **inference gateway**:
an Anthropic-compatible `CWS_PROFILE_<name>_BASE_URL` plus a token, which needs no
login at all. `install.sh --profiles` adds, renames or removes them; a profile you drop
keeps its `~/.claude-<name>` folder until you delete it yourself.

Each profile is a separate Claude Code config dir. Non-shared profiles symlink these
items to the shared profile, so every session, skill and MCP server is visible from
every profile and `claude-audit` sees all work in one place:

`projects sessions session-env history.jsonl file-history shell-snapshots skills plugins mcp`

Each profile keeps its own `settings.json` and login (`.claude.json`) — that is the
point of having several: e.g. `personal` on a Claude subscription, `work` on a company
gateway.

`install.sh` never merges data. If a non-shared profile already has a real
`projects/` (or any of the above), it warns and leaves it; move its contents into the
shared profile and re-run.

`~/.claude` is linked to the shared profile if it doesn't exist yet.

## MCP servers

`./install.sh --mcp` (and the first run) asks what you use:

| question | choices |
|---|---|
| email provider | Microsoft 365 / Outlook, Gmail / Google Workspace |
| communication channel | Microsoft Teams, Slack |
| Git provider | GitHub, GitLab, Azure DevOps, Bitbucket |
| documentation | Confluence, Notion, SharePoint / OneDrive, Google Drive, Slack |
| ticketing | Jira, Azure DevOps Boards, GitHub Issues, Linear, ServiceNow |
| cloud and data | Azure, Microsoft Fabric, Databricks, AWS |
| docs lookup | Microsoft Learn, AWS documentation, Context7 |

`mcp/catalog.json` maps each answer to vendor-documented MCP servers — nothing
company-specific is in it. The answers, and what the servers need to know about your
company (Azure DevOps organisation, GitLab host, Databricks workspace host and OAuth client
id, AWS region), are saved in `config.env` as `CWS_MCP_*`. **Secrets** (a GitHub token) are
asked for when a server is first set up and kept only in the profile's own `.claude.json`
(private, 0600) — never in `config.env` or the repo.

Every install then gives **each profile the same servers**, so profiles don't drift. It only
manages servers named in the catalog: it adds or updates the ones you chose and removes the
ones you no longer choose. Servers you added yourself under other names are left alone, and
so are settings it doesn't manage on its own servers (an OAuth client id, extra headers). It
backs up `.claude.json` to `.claude.json.bak-mcp` before changing it.

Some choices can't be set up as a local server — Microsoft 365 and Gmail sign in only through
your company's app registration — so the installer tells you to switch on the **claude.ai
connector** instead; Slack uses its own Claude plugin (`claude plugin install slack`), and
ServiceNow a server your admins host. Servers that sign in through the browser (Atlassian,
GitLab, Notion, Linear, Databricks, AWS) do it the first time you run `/mcp`.

`python3 mcp/configure.py show <config.env>` prints what your answers select.

## Transcript retention

Claude Code deletes transcripts it hasn't written to for `cleanupPeriodDays` days —
**30 by default**. Those transcripts are what `claude-audit`, the weekly review, the
daily recap, `claude-search` and the VS Code sidebar read, so `install.sh` sets
`"cleanupPeriodDays": 3650` (about ten years) in each profile's `settings.json` where
it isn't set. A value you set yourself is kept; if it is shorter, `install.sh` warns
that the audit will lose older sessions.

## Gateway tokens

With `CWS_PROFILE_work_BASE_URL="https://gateway.example.com"`, `install.sh` sets
`env.ANTHROPIC_BASE_URL` in `~/.claude-work/settings.json` and asks for the token
once, storing it as `env.ANTHROPIC_AUTH_TOKEN` in that file (mode 600). The token is
never written to the config or the repo. To change it, edit that `settings.json` or
delete the key and re-run `install.sh`.

## context.md — standing context

Copied into the work root's `CLAUDE.md` by `install.sh`, so every session in the work
root knows it without being told. It is inlined rather than imported: Claude Code does
not expand an `@import` in a parent `CLAUDE.md` for a session running in a sub-folder,
and every session runs several folders down. Put the stable facts Claude would
otherwise rediscover: tenants, subscription ids, workspaces, storage accounts, repo
locations, naming quirks, hard-won rules of thumb, how you like answers. Ids and names
only — no secrets. After editing it, run `./install.sh` to copy it into `CLAUDE.md`.

## review-rules.md — weekly-review house rules

Read by the `weekly-review` skill before it proposes anything; where it's more
specific than the skill, it wins. Typical content: the default task for unticketed
work, epics that catch a programme's work, tickets to ignore. Week-by-week decisions
don't go here — they are recorded in `_audit/review/ledger.json` by
`claude-audit --apply`.
