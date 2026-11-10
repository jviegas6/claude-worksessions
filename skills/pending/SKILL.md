---
name: pending
description: What still needs a reply from the user in Teams and mail, and what they are waiting on from other people, checked against the open topics in the work sessions. Use when the user asks what is pending, what needs their reply, who they are waiting on, or for an inbox sweep. Read only - nothing is created, drafted or sent.
---

# Pending

> **Settings.** Read `~/.config/claude-worksessions/config.env` once at the start (one `cat`; it is a link to `<work root>/_config/config.env`). `CWS_WORK_ROOT` is the work root every path below is relative to; `CWS_USER_ROLE` and `CWS_ORG` come from the same file. If the file is missing, ask for the work root in one question and stop.

One screen: what needs the user's reply, what they are waiting on, and whether each is
already tracked as an open topic. The user's role and organisation are `CWS_USER_ROLE` and `CWS_ORG` from the settings file.

**Read only.** Never draft, send, flag or label anything in Teams or Outlook. Never create a
request folder or set a waiting flag unless the user asks for that item by name, after seeing
the list.

Started by `claude-pending` (the sidebar's **What's pending?**), which runs this skill in the
work root with the session already on the no-audit list. Do not create a request folder for
this run.

## Step 1 - the window and the identity

Default window: since the start of the previous working day (Friday when today is Monday).
"Since yesterday", "last 3 days" or a date override it. Call `get_me` once: you need the user's
`mail` and `displayName` to tell their own messages from other people's.

## Step 2 - what is tracked already

Run `claude-sessions -a --json` and keep every request whose `waiting` is set: `on` (`me` |
`other`), `who`, `what`, `since`, `link`, and the request's name and path. These are the open
topics; the sidebar shows them under *Waiting on me* and *Waiting on someone*.

## Step 3 - Teams and mail

Use the Microsoft 365 tools: `teams_list_chats`, `chat_message_search`,
`teams_list_channel_messages` for Teams; `outlook_email_search` for mail. For each thread in
the window decide who the ball is with:

- **Needs my reply**: a question addressed to the user, a request only they can act on, a
  decision or approval asked of them, or a thread where someone is clearly waiting on them, and
  the user's own message is not the latest in it.
- **Waiting on them**: the user asked for something and nobody has come back since.
- **Neither**: FYI and thanks, automated notifications and newsletters, meeting invites, group
  chatter that asks nothing, threads already answered. Leave these out, do not list them.

Be strict. A welcome mail, a team sync, a daily chat and a handover note are not requests.

## Step 4 - match against the open topics

For each thread, look for an open topic on the same person and subject, the same Teams chat
(the chat id in the flag's link) or the same ticket. Say whether it is tracked, tracked but
stale (the flag says the other direction), or not tracked.

## Step 5 - report

Two short tables, newest first, nothing else:

```
Needs my reply
| who | what they need | where | since | tracked |

Waiting on them
| who | what I asked | where | since | tracked |
```

`tracked` is the request folder name, "stale: flag says waiting on me" or "no".

`claude-wait` is disabled (2026-11-04; waiting is tracked in Todoist): never run it, never
print a `claude-wait` command, and treat waiting flags as frozen history.

Then stop. If the user picks an untracked item, `claude-new -t <TICKET or Other> "<topic>"`
starts its folder. Only on request, one item at a time.
