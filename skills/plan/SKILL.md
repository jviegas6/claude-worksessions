---
name: plan
description: Open or start the request's plan as a DAG of steps (who, date, what has to happen, what can go wrong, check, rollback, dependencies) in the browser editor, and keep it current while the work goes on. Use when the user types /plan, asks to see, open, edit or start the plan, says they changed the plan or the DAG, or starts work that needs a plan first (more than 2 hours or other people involved).
---

# Plan

The request's plan lives in `plan.json` in the request folder. The user edits it in the browser
(`claude-plan` serves the editor); you read and update the same file. It is the source of truth
for the request: what has to happen, in what order, who does it, and where it stands.

## Open it

Run `claude-plan "$PWD"` from the request folder (never the work root). It starts the local
server if needed and opens the editor in the default browser; say so in one line. If the folder
is not a request folder, say so and stop.

## No plan yet

If there is no `plan.json`, offer to draft one from what the conversation already says, then write
it and open the editor. Start from the five lines the user wants before any long task: goal,
success (a number, a test or who approves), who, date, risk. Each step:

```json
{"id": "short-id", "title": "…", "who": "you|claude|others|external", "status": "todo|open|waiting|done|failed",
 "when": "YYYY-MM-DD", "does": "what has to happen", "risks": ["what can go wrong → how we'd notice"],
 "check": "how we know it worked", "rollback": "exact undo steps", "evidence": "file or link",
 "deps": ["ids of the steps it comes after"]}
```

Header: `ticket`, `title`, `goal`, `success`, `deadline` (`YYYY-MM-DD`), `nodes`. Every step that changes something
has a rollback, or says why it can't be undone. Every step has a date: a best estimate is better
than none. Order comes only from `deps`; there are no positions.

## Keep it current

- Before acting in a folder with a `plan.json`, read it.
- When a step starts, finishes, fails or changes, update its `status`, and `evidence` with the file
  or result that proves it. When the plan changes shape, add a `replan` line to the step where it
  changed, saying what changed and why. An incident goes in `incident`.
- Never overwrite the file blindly: read it, change it, write it back. Before writing, copy the
  current file to the next free `plan.vN.json`, the same way the editor does, so every version stays.
- The editor reloads by itself when the file changes and it has nothing unsaved; if the user has
  unsaved edits, it warns them instead.

## The user changed it

When the user says they changed the plan, read `plan.json`, compare it with the latest
`plan.vN.json`, and say in a few lines what changed (steps added, removed, moved, fields edited)
and what it means for the work: new risks, steps without a date or a rollback, broken order.

## ✨ suggestions

The editor's ✨ runs `claude -p` in the folder, read-only, and puts the reply on the clipboard. If a
request starting with `DAG-SUGGEST` ever reaches you in a session, reply with only the JSON it asks for.
