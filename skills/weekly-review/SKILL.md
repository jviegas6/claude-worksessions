---
name: weekly-review
description: Fill in the weekly functional-review tracker (Week, Task, Jira Ticket, Comments, phase flags, Leave, Meetings & Interactions, Utilization %) from Claude sessions, Teams chats, meetings, sent email, out-of-office and Jira, with a curated confirmation of which sessions belong with which meetings and emails, and which task each piece of work is. Use when the user asks for their weekly review, functional review, weekly tracker, utilisation for the week, or to "fill in my week".
---

# Weekly functional review

The output is rows for the user's weekly tracker: one row per (week, task, Jira
ticket), in the tracker's own column layout, ready to paste. Two judgement calls
sit in between — *which sessions belong with which meetings/emails*, and *which
task a piece of work is*. Both are settled with the user once and stored in the
review ledger (`_audit/review/ledger.json`), so each week only asks about what is
new. Getting that curation right is the whole job; the arithmetic is the script's.

Paths below are relative to `{{CWS_WORK_ROOT}}`.

**Read `_config/review-rules.md` first** if it exists: it holds the user's own
house rules (which epic catches which work, the default task, tickets to ignore).
Where it is more specific than this skill, it wins.

## 0 — The week

Resolve to a date in the target week; `claude-audit --week` normalises to Monday.
Default: this week from Thursday on, otherwise last week. Say which week you chose.

## 1 — Evidence for every weekday

Each Mon–Fri needs `_audit/activity/YYYY-MM-DD.json`. The daily recap writes these;
gather any that are missing using the workday-recap rules (time-zone
normalisation, the user's own messages only, chat bursts collapsed to one row).
Never overwrite an existing day file — it may hold confirmed subjects.

Classify calendar entries for the weekly view:

- `"source": "leave"` — out-of-office blocks that are all-day or four hours or more
  (`showAs: "oof"`), including multi-day blocks that began before the week. Put
  the block in the file of the first weekday it covers. The calendar is the only
  OOO source: the connector can *set* automatic replies but has no tool to read them.
- `"source": "personal"` — lunch, focus time. Visible, never counted.
- `"source": "notice"` — tentative or free entries, change windows and
  announcements (e.g. patching change windows). When two meetings clash, the one
  not accepted is a notice. Visible, never counted.

Chat search hits Graph rate limits (429) on busy days: fetch one day at a time,
page with `nextOffset`, and say where coverage is partial.

## 2 — Jira context (read-only)

Refresh `_audit/review/jira.json` as `[{key, summary, status, updated, mine}]` from:

```
searchJiraIssuesUsingJql(cloudId="{{CWS_JIRA_CLOUD_ID}}",
  jql='(assignee = currentUser() OR reporter = currentUser() OR watcher = currentUser())
       AND updated >= "<week start minus 60 days>" ORDER BY updated DESC',
  fields=["summary","status","updated","assignee"], maxResults=100)
```

`mine` is true when the assignee is the user; keep `updated` as the full timestamp
(`2026-09-11T07:10:05+01:00`). The reconciliation uses both. The result is large
and lands in a file — parse it with python, don't read it raw.

## 3 — Propose

```
claude-audit --week YYYY-MM-DD --propose
```

Prints the undecided correlations and task mappings in tiers and writes
`_audit/review/proposals_<monday>.json` with the keys you need to record answers.

## 4 — Curate: the script's scores are evidence, the tiers are yours

The user asked for two processes: correlations you are confident in, which only
need a confirmation, and ones you think are related, which need their input. The
script's tiers are a starting point. Before asking anything:

- **Promote** a "possible" link into the confirm batch when the match is plain on
  reading — the same topic in both titles plus timing (a "Delete secrets" email
  sent minutes before a "Delete secrets" session). **Demote** a "likely" one that
  reads wrong. **Time alone is never enough** — a long session overlaps half the
  day's meetings.
- **Propose a task and ticket for every unmapped subject yourself**, from session
  titles and prompts, folders, Jira summaries, the tracker's existing tasks and
  what the ledger already holds. **Apply the house rules in `review-rules.md`** —
  typically an epic that catches all work on a programme (calls, standups,
  investigations) unless it is a specific task with its own ticket. The ledger
  records such an epic as the task's `default_ticket`, so a subject on that task
  mapped to `Other` lands on the epic anyway.
- **The session's task type is evidence.** `claude-new` records what kind of work a
  session is (permissions, job errors, ...); it shows in the detail CSV's `task_type`
  and per row in `task_types` in the breakdown. Use it to tell two subjects apart and
  to write the row's comment. It never overrides a declared ticket.
- **Declared tickets are facts.** A session started with `claude-new -t` carries its
  ticket; if the ledger already knows which task owns it, the subject is mapped and
  you do not ask. If the ticket is new, ask only which task it belongs to.
- **Unticketed work defaults to the ledger's `default_task`** — the placeholder
  for everything that doesn't have a ticket, including team dailies, all-hands
  and 1:1s. The script suggests it for any subject with no ticket evidence; it is
  a suggestion, not an automatic mapping, because some ticketless work has a real
  home the user has confirmed before (programme work → its epic). Once confirmed,
  the ledger remembers the exception.
- **Do not propose `(ignore)`.** The user wants all of their work counted: anything
  without a ticket goes to the default task, tooling and setup work included.
  Use `(ignore)` only when the user asks for it.

Then ask in as few rounds as the week allows, printing each table as text just
before the question that refers to it:

1. **Correlations.** The confirm batch as a numbered table (session ↔ events, one
   line of evidence each) with one question: *Confirm all* / *Let me exclude some*
   (they name numbers via Other). Then the uncertain ones grouped by session: one
   multiSelect question per session whose options are its candidate event groups,
   up to four questions per call.
2. **Task mapping.** One table: subject · hours · items → task / ticket, marked ✓
   where declared or clear, ? where it is your guess. One question: *Confirm all* /
   *Correct some* (they write e.g. "U3 → (ignore); U9 → BI Migration / Other").
3. **Columns E–M, every row.** Show the rows with all nine columns, not just task,
   ticket and %. The script infers E–K per row from that week's work using the
   tracker's own header definitions, and records the words behind each flag in
   `flag_evidence` in the detail CSV — use it to judge and to explain. Correct what
   reads wrong (a keyword can mislead), then one question: *Confirm* / *Correct
   some*. Ask about **Completed** only where there is a reason — the row's
   `jira_status` moved to Done / Closed / UAT that week, or the user said a
   deliverable was finished. Confirm detected leave, and the comment per row in
   the tracker's terse style. Confirmed values are stored as the week's overrides.

## 5 — Record

Write the answers to `_audit/review/decisions_<monday>.json` and run
`claude-audit --apply` on it. Shape:

```json
{"assign":   [{"key": "<session_key or event_key>", "subject": "<subject name>"}],
 "reject":   [["<session_key>", "<event_key>"]],
 "subjects": [{"subject": "<subject name>", "task": "<task>", "ticket": "{{CWS_TICKET_EXAMPLE}}"}],
 "tasks":    [{"task": "...", "tickets": ["..."], "keywords": ["..."], "paths": ["..."],
               "flags": {"hld": "Yes"}, "comments": {"{{CWS_TICKET_EXAMPLE}}": "Calls, generic support"}}],
 "weeks":    {"YYYY-MM-DD": {"leave_days": 2,
               "rows": {"<task>|<ticket>": {"comments": "...", "flags": {"hld": "Completed"},
                                            "utilization": 40}}}}}
```

- A confirmed link assigns **the session key and every event key** in the group to
  one subject name. A rejected link goes in `reject` as [session_key, event_key]
  for each event, so it is never proposed again.
- Map subjects **by the name they will have after your assigns** — the subject id is
  a hash of the name, and a mapping only carries into next week if the name is the
  same. Keep names stable and descriptive of the work, not of an invite.
- A new ticket on a known task is added to that task automatically.

## 5b — Reconcile against Jira

```
claude-audit --week YYYY-MM-DD --reconcile
```

Both directions: what each ticket got, and which tickets assigned to the user
changed that week with nothing booked to them. Ask about every **?** row — a
ticket with no activity but an activity that looks like it, booked elsewhere
(e.g. a session booked on an epic while the ticket it really belonged to was
being closed, or project mail booked on the default task). Re-map with `--apply` if
the user agrees. **x** rows are tickets that moved with no visible activity —
usually work done in Jira itself; mention them, don't guess.

## 6 — Produce

```
claude-audit --week YYYY-MM-DD              # the rows, every column, in the terminal
claude-audit --week YYYY-MM-DD --detail     # every activity behind them, with task and ticket
claude-audit --week YYYY-MM-DD --csv        # save: _audit/claude-audit_week-<monday>_summary.csv
                                            # plus _breakdown.csv (hours, flag evidence, row_id)
```

When the user is about to paste, suggest `--copy`: it copies the rows tab-separated,
without a header, for the first empty tracker row. It overwrites whatever they had
copied, so it's theirs to run (or yours when asked). A month is `--month YYYY-MM`:
one block per week that starts in it.

`--detail` covers exactly the days the summary covers and ends with a reconciliation
line: `duration_exact` summed by `row_id` equals each summary row's hours to the
second. If it ever says "does NOT reconcile", report that to the user — it is a bug.

The terminal table and the CSV carry a **Task Type** column (the type most of the
row's time carries); `--copy` leaves it out, because the clipboard has to match the
tracker's own columns — pass `--with-type` if the tracker has gained a Type column, or
`--no-type` to drop it everywhere. `claude-audit --week YYYY-MM-DD --by-type` gives the week's
split by type — worth a line in what you report.

Show the rows. Then state plainly anything the run flagged: unmapped hours must
be **zero** before the rows are pasted, and minor subjects left out.

## Rules

- **Never paste guesses.** Unmapped time is kept out of the rows; resolve it or map
  it to `(ignore)`.
- Utilisation is the share of **tracked** time — sessions, meetings, correspondence —
  not of a 40-hour week. Leave takes days ÷ 5 first; the rest is split by largest
  remainder in 10% steps. **Every worked row shows a percentage** — the user's rule,
  0% makes no sense for work that happened. Each row gets at least one step, taken
  from the row rounded up the most; if there are more rows than steps left after
  leave, the week drops to 5% steps.
- Columns E–K come from **evidence**, per row, per week — not fixed per task. The
  definitions are the tracker's header row: E Assessments / Roadmaps / Reference
  Architectures / Security / Standards, F Func Spec support, G HLD delivered,
  H LLD support, I Development support (a session that changed code counts),
  J Post-deployment support, K Production issue support. Rituals (standups,
  all-hands, 1:1s, syncs) only set M, Meetings & Interactions. `Completed` comes
  only from the user.
- Never re-ask anything the ledger already holds. If the user changes their mind,
  apply a new decision — it overwrites the old one.
- Tickets in the ledger's `ignore_tickets` are never matched or suggested (see
  `review-rules.md` for the user's list). Record any new one with `"ignore_tickets"`
  and `"remove_tasks"` in a decisions file.
- **Small subjects are counted, never left out, and never asked about.** Anything under
  `--min-subject` (10 min) that isn't mapped goes to its best-matching task on that
  task's default ticket — programme work to its epic — otherwise to the default
  task. They show as `auto_mapped` in the detail CSV; glance at them, and
  map any mis-filed one explicitly.
- Read-only everywhere except the ledger and the output files.
