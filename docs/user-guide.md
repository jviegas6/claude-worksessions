# claude-worksessions — User guide

How to use claude-worksessions day to day, organised by task. For every flag of every command
see [Commands](commands.md). For how it works inside see the [High-Level Design](hld.md) and
the [Low-Level Design](lld.md).

- [1. What it gives you](#1-what-it-gives-you)
- [2. Installing and first setup](#2-installing-and-first-setup)
- [3. Starting a piece of work](#3-starting-a-piece-of-work)
- [4. Working in a session](#4-working-in-a-session)
- [5. Coming back to work](#5-coming-back-to-work)
- [6. Working from VS Code](#6-working-from-vs-code)
- [7. Finding past work](#7-finding-past-work)
- [8. Where your time went: the audit](#8-where-your-time-went-the-audit)
- [9. The daily recap and the weekly review](#9-the-daily-recap-and-the-weekly-review)
- [10. Improving how you prompt](#10-improving-how-you-prompt)
- [11. Tidying up](#11-tidying-up)
- [12. Sharing results by email](#12-sharing-results-by-email)
- [13. Profiles](#13-profiles)
- [14. Updating, moving computer, uninstalling](#14-updating-moving-computer-uninstalling)
- [15. Troubleshooting](#15-troubleshooting)

---

## 1. What it gives you

claude-worksessions wraps Claude Code so that every piece of work is organised, findable and
accounted for, without you maintaining anything by hand:

| You get | Because |
|---|---|
| **One folder per request**, `YYYY/MM/DD/HH-mm-ss_slug/`, holding notes, scripts and outputs | `claude-new` creates it and starts Claude there |
| **The ticket, task type and goal recorded** with each piece of work | `claude-new` asks for them and writes `.session.json` |
| **Several Claude accounts** (a subscription, a company gateway) sharing **one history** | profiles, one shared |
| **Your time** per day, week or month, per ticket and task type | `claude-audit` reads the Claude transcripts |
| **Search** across every past session | `claude-search` |
| **A daily recap and a weekly tracker** filled from Claude, Teams, calendar, mail and Jira | the `workday-recap` and `weekly-review` skills |
| **Guard rails** on how Claude works: asks when a request is vague or something doesn't exist; stays on the request | the prompt-quality hooks and `claude-guard` |
| **A sidebar in VS Code** listing requests and sessions, each session in its own tab and profile | the Work sessions extension |

The *work root* (for example a `work_sessions` folder in OneDrive) holds all of it, so it
syncs to your other machines.

---

## 2. Installing and first setup

```sh
git clone https://github.com/jviegas6/claude-worksessions.git ~/Repos/claude-worksessions
cd ~/Repos/claude-worksessions
./install.sh
source ~/.zshrc
```

The installer asks, once:

1. **Where the work root goes.** Choose a synced folder if you use more than one machine.
2. **Your organisation, role, time zone and an example ticket key** (such as `PROJ-123`).
   These go into the skills and the `CLAUDE.md` every session reads.
3. **Your profiles.** Each is either a *Claude subscription*, where you sign in, or an
   *inference gateway*, where you give a base URL and a token. Add as many as you need.

It installs what's missing (Homebrew packages on a Mac, apt/dnf/pacman/zypper on Linux), and
offers to open each subscription profile so you can sign in.

Then fill in two files in `<work root>/_config/`:

| File | What to put there |
|---|---|
| `context.md` | The stable facts Claude would otherwise rediscover every time: tenants, subscriptions, workspaces, repos, naming quirks, how you like answers. No secrets. Run `./install.sh` again after editing it, so it's copied into the work root's `CLAUDE.md`. |
| `review-rules.md` | Only if you use the weekly review: your default task for unticketed work, epics that catch a programme's work, tickets to ignore. |

Everything else in [Configuration](configuration.md) has sensible defaults.

---

## 3. Starting a piece of work

Start every request with `claude-new`:

```sh
claude-new -t PROJ-123 "vnet peering issue"
```

It asks for anything you didn't give:

| Question | Answer with |
|---|---|
| Jira ticket | `PREFIX-123`, or `Other` when there's none (mandatory) |
| Profile | a number from the menu, or `-p work` on the command line |
| Task type | what kind of work *starts* this (permissions, job errors, new features…). Enter takes the suggestion |
| Goal | what the session should deliver. Enter uses the name |
| Done when | how you'll know it's finished. Optional |
| Count it in the review? | Enter for yes. `n` (or `-n`) for experiments you don't want in your time report |

It then creates the folder, records all of that in `.session.json`, moves you into it and
starts Claude with the chosen profile. The folder is announced as, for example,
`→ work  PROJ-123  [job errors]  2026/09/27/14-05-00_vnet-peering-issue`.

Shortcuts:

```sh
claude-new PROJ-123 cost pipeline          # a ticket-shaped first word is the ticket
claude-new -t Other -p personal -T tooling -g "list the job's sources" quick check
claude-new --prompt /weekly-review weekly  # start straight into a skill
claude-new -c -t PROJ-9 "report"           # open the new folder in VS Code instead
```

**The task type is the trigger, not the detours.** A job error that needs an investigation,
a permission change and a documentation update is `job errors` throughout.

---

## 4. Working in a session

Work as you normally would with Claude. A few things happen on their own:

- **Everything Claude writes for this request belongs in the request folder.** The work root's
  `CLAUDE.md` tells it so.
- **Vague first requests** ("check the permissions") get a nudge for Claude to ask you one or
  two questions before doing substantial work.
- **When something turns out not to exist** (a table, a group, a resource), Claude is told to
  confirm the name and environment with you instead of hunting for alternatives.
- **claude-guard**, when switched on, keeps the session on its goal. It flags a prompt that
  starts a new objective, work in another request's folder, and repeated calls. See the
  [claude-guard user guide](guard/user-guide.md).

When the work **changes kind** (what looked like a job error was really a permissions
request), change the type:

```sh
claude-type permissions            # this session only
claude-type --folder permissions   # the folder's default
```

When the **objective changes on purpose**, re-anchor it:

```sh
claude-goal "survey the access-control options" --done "a comparison table"
```

When it's really **a separate piece of work**, start a new request with `claude-new` instead.
A clean folder and context keep both findable.

---

## 5. Coming back to work

| To… | Do |
|---|---|
| jump to a request folder | `ws` (fuzzy search, newest first). `ws -c` opens it in VS Code, `ws -o` in Finder, `ws -y` in yazi |
| resume a session | `claude-resume -p work --resume <id>`, or `claude-resume -p work` for Claude's picker |
| see your latest sessions | `claude-sessions` (the last 30), `claude-sessions -a` for all |
| list recent requests with their tickets | `claude-new -l` |

Sessions from every profile are visible from every profile, because the profiles share one
history.

---

## 6. Working from VS Code

If you use VS Code, open **one window on the work root** and use the **Work sessions** sidebar
(the history icon):

- **Requests and their sessions**, grouped by day or ticket, or as a flat list of recent
  sessions. Sort by last activity, start time or name.
- **Click a session** to open it in an editor tab running `claude-resume` with its own profile
  and folder, so requests on different profiles sit side by side.
- **+** at the top starts a new request (`claude-new` in a tab). **+** on a request starts a
  new session in it.
- **Files** under a request lists the folder's files. Click to open (Markdown in the preview).
  Requests with no session yet show too.
- **Search box**: type to filter by title, prompts, ticket, type, profile, folder or file names.
  Press Enter to run `claude-search`, which also searches inside conversations. When the search
  narrows a request's files, the label says so (`Files 1 of 4`).
- **Funnel**: filter by day, ticket, or whether a session left artifacts.
- **Pin** requests or sessions to keep them at the top. Pins sync with the work root.
- **Right-click** for: set task type, reveal in Finder, delete a session with no value, copy a
  Markdown file for email.
- **Command Palette → Work sessions**: audit, search, go to request, run a skill, resume by id.

If you prefer one window per request, `claude-new -c` or `ws -c` opens the request folder
itself, and the Claude extension there runs with that request's profile.

---

## 7. Finding past work

```sh
claude-search PROJ-123
claude-search "vnet peering" --from 2026-09-01
claude-search "why did the nightly load fail" --ai     # Claude judges relevance
```

Results are ranked across session titles, your prompts, Claude's replies, commands that were
run, and linked meetings and mail. Each comes with the command to resume it, and you can
pick one to resume straight away. `--csv FILE` exports the list.

In VS Code, press Enter in the sidebar's search box to do the same.

---

## 8. Where your time went: the audit

```sh
claude-audit                    # this week, one row per task and ticket
claude-audit --day              # today
claude-audit --month 2026-09    # a month
claude-audit --from 2026-09-01 --to 2026-09-15 --detail   # every activity behind the numbers
claude-audit --week --by-type   # hours per task type
claude-audit --week --copy      # onto the clipboard, in your tracker's columns
claude-audit --week --csv       # a CSV in <work root>/_audit/
```

Time is measured from the Claude transcripts: the time you actually worked, with long stalls
capped. Meetings, mail and chats saved by the recap and review skills are merged in. The
profile, ticket and type of each session come from its `.session.json`, which is why sessions
should start with `claude-new`.

Sessions started with `claude-new -n` (or listed in `_audit/no-audit.txt`) are left out.
`claude-search` still finds them.

---

## 9. The daily recap and the weekly review

Both are Claude skills. Start them in their own request so they get a folder, ticket and type:

```sh
claude-new --prompt /workday-recap -t Other "recap"
claude-new --prompt /weekly-review -t Other "weekly review"
```

In VS Code: Command Palette → *Work sessions: Run skill…*.

- **workday-recap** rebuilds one day in time order from your Claude sessions, Teams chats,
  calendar and sent mail. Use it for stand-up notes, a timesheet, or to see where a day went.
- **weekly-review** fills your weekly tracker (task, ticket, comments, phase, leave, meetings,
  utilisation) from sessions, Teams, calendar, mail, out-of-office and Jira. It asks only about
  what's new or ambiguous, and records its decisions so next week starts from them.

They need the Microsoft 365 and Atlassian connectors, which come with your Claude account once
you're signed in. House rules for the review go in `_config/review-rules.md`.

---

## 10. Improving how you prompt

```sh
claude-retro                 # the last 7 days
claude-retro --week          # last week
claude-retro --no-judge      # just count the friction, no Claude calls
```

`claude-retro` finds where work stalled: something that didn't exist, a correction ("no, I
meant…"), an interruption, a rejected tool call, a reversal, a clarifying question. It ties
each to the prompt before it, and has Claude judge whether the prompt caused it and write a
better one. The report and a week-by-week trend go to `<work root>/_audit/quality/`. Habits
worth keeping belong in `_config/context.md`.

For keeping sessions on their goal as you work, see [claude-guard](guard/user-guide.md).

---

## 11. Tidying up

Test sessions and other noise can go to a bin you can restore from:

```sh
claude-delete <id> --check     # may it go, and what would that mean?
claude-delete <id>             # say what goes, ask, then move it to the bin
claude-delete --list           # what's in the bin
claude-delete --restore <id>   # put it back
claude-delete --empty          # delete everything in the bin for good
```

A session may go only when it has **no value**: none of the files it wrote still exist, or it
was kept out of the review. Sessions booked by the weekly review, open in a Claude process,
or written to in the last two minutes are never deleted. Files a session wrote are never
touched.

In VS Code: right-click a session → **Delete session…**. The **Deleted** group at the bottom
lists the bin.

---

## 12. Sharing results by email

```sh
claude-md-email findings.md          # formatted onto the clipboard: paste into Outlook
claude-md-email findings.md --open   # open as a web page instead
```

Black on white, Calibri, bordered tables, whatever your editor's theme. In VS Code: the
envelope button on a Markdown file or its preview (**Copy for email**). In yazi: `Enter` on a
`.md` opens it as HTML.

---

## 13. Profiles

A profile is a Claude Code configuration folder, `~/.claude-<name>`: a subscription login, or
a gateway URL and token.

- `claude-new -L` lists them. `claude-new -p <name>` and `claude-resume -p <name>` use one.
- A bare `claude` uses the default profile.
- One profile is **shared**: it owns history, projects, skills, plugins and MCP settings, and the
  others link to it. A session started under any profile can be resumed and found from any
  other.
- `./install.sh --profiles` adds, removes or changes profiles.

---

## 14. Updating, moving computer, uninstalling

```sh
cd ~/Repos/claude-worksessions
./install.sh --update      # the newest release, then re-install
./install.sh --edge        # follow main instead of releases
./install.sh --dry-run     # show what would change
```

Your work root, `_config/`, profiles and history are never touched by an update.

To move to a new computer, see [New computer](new-computer.md). The short version: sync the
work root, clone the repo, run `./install.sh` pointing at the existing `_config/config.env`,
and sign in.

`./uninstall.sh` removes the commands, hooks, shell block and extension. Your work root and
profiles stay.

---

## 15. Troubleshooting

| Symptom | Fix |
|---|---|
| `claude-new: command not found` | open a new terminal, or `source ~/.zshrc` |
| A session is missing from the audit or has no ticket | it didn't start with `claude-new`, or ran outside a request folder. Start sessions with `claude-new` |
| Time shows under the wrong ticket or type | fix `.session.json` in the request folder (`claude-type` for the type); the audit re-reads it every time |
| The VS Code sidebar is empty or stale | *Developer: Reload Window*; check `claudeWorksessions.sessionsCommand` points at `claude-sessions` |
| The Claude extension in VS Code uses the wrong profile | open the request folder as the workspace (`ws -c`), so `claude-vscode` can read its `.session.json` |
| The weekly review can't see Teams, mail or Jira | sign in to the profile it runs under and check the connectors in Claude |
| `claude-md-email` fails | install `pandoc`; on Linux, `wl-copy` or `xclip` for the clipboard |
| Hooks feel wrong | `/hooks` in Claude Code lists them. For the guard, see its [troubleshooting](guard/user-guide.md#8-troubleshooting) |
