---
name: workday-recap
description: Reconstruct what the user actually did on a work day by pulling Teams chats, calendar meetings, sent emails, and Claude Code sessions into one chronological picture. Use when the user asks what they did today or on a given date, wants a daily or weekly recap, standup notes, a timesheet entry, or an activity report for auditing.
---

# Workday recap

Build an honest picture of one work day from four sources, then write it up.
The user is a {{CWS_USER_ROLE}} at {{CWS_ORG}}; the point is a defensible record of
where the day went, not a flattering narrative.

## Step 0 — establish the day and the identity

Resolve the target date to an explicit `YYYY-MM-DD` before doing anything else.
"Today" is fine; "yesterday" and weekday names must be converted to a real date.
Default to today when the user gives no date.

Call `get_me` once. You need the user's `mail` and `displayName` to tell their
own messages apart from other people's — several sources return everyone's
activity, not just theirs.

## Step 0.5 — normalise the clock before merging anything

**The four sources do not agree on time zone.** Merging them raw produces a
timeline that is silently an hour wrong for half its rows. Convert everything to
the user's local time ({{CWS_TIMEZONE}}) before sorting:

| source | field | zone as returned | to do |
|---|---|---|---|
| `claude-audit` | `start` / `end` | already local | use as-is |
| calendar | `start.dateTime` | wall clock in `start.timeZone` (`{{CWS_TIMEZONE_WINDOWS}}` = {{CWS_TIMEZONE}}, daylight saving included) | use as-is, never re-read as UTC |
| email | `sentDateTime` | UTC (`Z`) | convert to local |
| chats | `createdDateTime` | UTC (`Z`) | convert to local |

Sanity-check the result: an email or chat that discusses what a Claude session
was doing should land *inside* that session's window. If it lands exactly an
hour off, the conversion is wrong.

## Step 1 — Claude sessions

```
claude-audit --day YYYY-MM-DD --sessions --csv -
```

This is the most reliable source: it reads the local transcripts. Columns that
matter are `start`, `end`, `worked_exact`, `worked_h`, `title`, `folder`,
`profile`, `task_type`, `cost_usd`. Use `title` as the name of the piece of work.

Read the numbers correctly: `elapsed` is wall-clock and is **not** time worked —
a session left open overnight shows hours. Quote `worked_exact` for the real
figure and `worked_h` (rounded up to the half hour) when the user wants billable
time. Sessions are split per day, so one that ran past midnight shows its part of each day.

## Step 2 — meetings

```
outlook_calendar_search(query="*", afterDateTime="YYYY-MM-DD 00:00",
                        beforeDateTime="YYYY-MM-DD 23:59", limit=25, order="oldest")
```

Each event's `start`/`end` come back as `{dateTime, timeZone}` where `dateTime`
is wall-clock **in that named time zone**. Present it as given; never re-read it
as UTC.

The calendar shows what was *scheduled*, not what was attended. Do not claim the
user attended a meeting. If a Teams meeting chat has messages from them during
the slot (step 3), that is evidence of attendance — say so, and otherwise
present meetings as booked time.

## Step 3 — Teams chats

```
chat_message_search(query="*", afterDateTime="YYYY-MM-DD 00:00",
                    beforeDateTime="YYYY-MM-DD 23:59", limit=25)
```

Two things to get right:

- Results include messages from **every participant**, not just the user. Split
  them: what the user said is activity; what others said is context. Match on
  `from.displayName` against the `displayName` from `get_me` — this path returns
  `from.email: null` (it says so in `searchInfo.fieldsUnavailable`), so an
  address match silently matches nothing.
- `summary` is HTML. Strip the tags before quoting a message.
- Chat bursts are the best evidence of what the user was actually arguing about;
  a run of short messages in one chat is one conversation, so summarise it as a
  thread with a topic rather than listing every line in the timeline.
- With date filters set this uses a per-chat scan: at most the 50 most recently
  active 1:1/group/meeting chats, 50 messages each, and **no channel messages**.
  The response opens with a `searchInfo` item saying which path ran and what it
  covered, and warns when results are partial. Read it, and pass any limitation
  through to the user rather than implying full coverage.

Paginate with `nextOffset` when the day is busy.

## Step 4 — emails sent

```
outlook_email_search(folderName="Sent Items", afterDateTime="YYYY-MM-DD 00:00",
                     beforeDateTime="YYYY-MM-DD 23:59", limit=25, order="newest")
```

With `folderName` set, use date filters **or** a free-text `query`, not both.
Report who each mail went to and what it was about; a long thread to one person
is a different signal from a broadcast.

Only pull received mail if the user asks — "emails sent" is what they specified,
and inbox volume says more about other people's day than theirs.

## Step 5 — write it up

Produce, in this order:

1. **Headline** — one or two sentences: the shape of the day and what dominated it.
2. **Timeline** — every item from all four sources merged in chronological order,
   as a table with time, source, and what happened. This is the core of the
   recap; it is what makes the day legible.
3. **Where the time went** — Claude session `worked_exact` totals grouped by
   topic **and by task type** (`claude-audit --day YYYY-MM-DD --by-type`: permissions,
   job errors, new features, ...; sessions with no type show as `(no type)`), plus
   scheduled meeting hours. A type names what *triggered* a session, so a day of
   `job errors` may well contain the permission changes and write-ups those errors
   caused — say that rather than implying the day held no permissions work. Give the two separately; they overlap
   (a session can run during a meeting) so do not add them into a single "total
   hours worked" figure and present it as fact.
4. **Threads still open** — questions asked of the user that they did not answer,
   sessions that ended mid-task, meetings with actions. Best-effort, and labelled
   as inference.

   A **parked session** is the most reliable item here, and worth flagging every
   time: `worked_exact` far below `elapsed` (roughly under a fifth) means the
   session sat open with little happening in it — work started and abandoned
   rather than finished. Name it and ask; the user knows, and their answer turns
   an inference into a fact. Once confirmed, mark it confirmed in the file and
   drop the inference label — a recap that is revised as facts arrive is the
   point of keeping it.
5. **Coverage** — state plainly what was not visible: Teams channels, chats
   beyond the scan window, work done outside Claude and Outlook. A recap that
   hides its blind spots is worse than useless for auditing.

## Step 6 — export the merged CSV

The prose recap is for reading; the CSV is for auditing. `claude-audit` cannot
reach the Microsoft 365 tools, so **you** hand it the meetings, emails and chats
you gathered and it does the merge:

1. Write the events to `{{CWS_WORK_ROOT}}/_audit/activity/YYYY-MM-DD.json` in the
   schema `claude-audit --schema` prints. Times must already be **local**
   (step 0.5) — the script trusts them and only attaches the local zone.
2. Run:

```
claude-audit --day YYYY-MM-DD --detail          # every activity, with task and ticket
claude-audit --day YYYY-MM-DD --detail --csv    # saved as _audit/claude-audit_<day>_detail.csv
```

It always reads `_audit/activity/`. Each row carries `event_id`, `subject_id`,
`session_id` and `row_id` — the weekly summary row it rolls up into
(`claude-audit --week … --csv` writes those rows plus a `_breakdown.csv` keyed by
`row_id`). Ids are content-derived: identical on every re-run, and a `subject_id`
is the same across days whenever the subject name is, so keep names stable.
`duration` (rounded up to the half hour) and `duration_exact` (unrounded) are on
each subject's first row per period (the day, or each week); `duration_exact`
summed by `row_id` equals
the summary's hours, and the detail view prints that reconciliation check.

Collapse chat bursts before writing them out — a run of messages in one chat with
gaps under ~30 minutes is one conversation and becomes one row, with the message
count and topic in `detail`. Do not emit a row per message.

Classify calendar entries that are not meetings you attend — the weekly review
reads these day files, so the classes matter:

- `"source": "leave"` — out-of-office that is all-day or four hours or more
  (`showAs: "oof"`), including multi-day blocks; the weekly review turns these into
  Leave days. Put a multi-day block in the file of the first day it covers.
- `"source": "personal"` — lunch, focus time, other short self-booked blocks.
- `"source": "notice"` — tentative or free entries, change windows and
  announcements (e.g. patching change windows, which can run for many hours). When two
  meetings clash, the one not accepted is a notice.

All three show in the timeline and none is ever billed or counted as meeting time.

### Linking events into subjects

**This is the part only you can do, and it is the point of the merged export.** A
meeting or an email often triggers the Claude session that does the work; those
belong to one unit, not three unrelated rows. Set `"subject"` on each event, and
map session ids to subjects in the `"subjects"` object:

```json
{"events": [{"source": "meeting", "...": "...", "subject": "Cost pipeline (Jane)"}],
 "subjects": {"99c5b9fa-77bf-4d4d-b840-d6bd4e79b08b": "Cost pipeline (Jane)"}}
```

Get session ids from `claude-audit --day YYYY-MM-DD --sessions --csv -` (`session_id` column).

Evidence that two events are one subject, strongest first:

- **A session's output appears in an email or chat** shortly after it ends — a
  "Failed pipelines audit" session followed 30 minutes later by a "178 failures"
  mail is the same work.
- **A session starts during or shortly after a meeting** whose subject or agenda
  names the same system. "Roadmap + cost pipeline" at 14:30 → "Billing table
  comparison" session at 14:53.
- **Same subject line** across emails (`Re:` chains) — always one subject.
- **Same chat, same topic**, even across separate bursts.
- **Same counterparties plus the same system named** in both.
- **The same task type** on both sides is weak support, never evidence on its own.

Name the subject after the work, not the meeting invite: "Cost pipeline
(Jane Doe)" beats "Roadmap + cost pipeline". Keep names stable
across days so a week can be grouped.

**Do not force links.** Time adjacency alone is not evidence — a recurring
standup covers many topics and rarely owns the session that follows it. An
unlinked event is its own subject, which is a perfectly good answer. In the prose
recap, say which links were inferred so the user can correct them; a correction
is cheap because the activity JSON is kept and can be re-run.

### How `duration` is computed

Per subject, rounded up to `--round-to` (default 30 min), written on the
**first row only** so the column sums straight down to a day total:

- session `worked_exact` counts in full;
- a meeting adds its booked time **only** if no session in the same subject was
  running through it — otherwise the same clock is counted twice;
- a subject made only of emails/chats is measured like `worked`: each burst's own
  span plus the gaps between messages, each gap capped at `--read-cap`. A lone
  email is an instant and costs nothing; two mails three hours apart are two
  minutes, not three hours;
- anything else with no measured time stays at 0.0.

**Never sum `worked_h` and `scheduled_h`.** They overlap: a session can run
through a meeting,. Report them as two figures.

Write the prose recap to `{{CWS_WORK_ROOT}}/_daily/YYYY-MM-DD.md`
(create `_daily/` if needed; the leading underscore keeps it out of `claude-new -l`).
Then print the headline, the timeline, and the coverage note in the terminal, and
say where the file went. Do not create a request folder for a recap — it is
infrastructure, not a request.

## Rules

- **Never invent activity.** If a source returns nothing for the day, say it
  returned nothing. An empty calendar is a real finding.
- Distinguish evidence from inference everywhere. "Sent 4 emails" is evidence.
  "Spent the morning on the billing migration" is inference from session titles.
- If a tool call fails (a missing Graph scope, a 403), report which source is
  missing and carry on with the rest. A partial recap that names its gap is
  useful; a silent one is not.
- Read-only. Never send mail, post to Teams, or change a calendar entry while
  building a recap.
- For a week or a date range, run the same steps per day but lead with the
  cross-day pattern; do not paste seven full timelines unless asked.
