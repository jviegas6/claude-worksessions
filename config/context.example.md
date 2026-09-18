# Standing environment context

<!--
  Copied to <work root>/_config/context.md by install.sh and imported into the
  work root's CLAUDE.md, so every session starts knowing it. Put here the stable
  facts Claude would otherwise rediscover each time: tenants, subscriptions,
  workspaces, storage, repos, naming quirks, your working preferences.
  No secrets — ids and names only.
-->

Most work here is <your stack, e.g. Databricks + Azure + networking>. The facts below
are stable — use them instead of rediscovering them. Verify before relying on any of
it for a destructive action, and correct `_config/context.md` when something changes.

## Azure

Tenant `<tenant-id>`. Everything below is **<region>**.

| Subscription | ID |
|---|---|
| <SUB_PROD> | `<subscription-id>` |
| <SUB_TEST> | `<subscription-id>` |

## Workspaces / services

| Name | ID | Network | Subscription |
|---|---|---|---|
| <workspace> | <id> | <vnet> | <SUB_PROD> |

## Repositories

- `<path to repo>` — what it is, where the important bits live

## Rules of thumb

- <hard-won facts that save time, e.g. which error means network vs RBAC>

## Working preferences

- Answer the technical question asked.
- Concise and direct. No restating what was already established.
