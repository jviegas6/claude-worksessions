// The sidebar's data model, kept free of the vscode API so `node --test` can check it.
// Input is `claude-sessions -a --json`: { work_root, sessions: [{ id, mtime, cwd, in_work_root,
// title, first_prompt, last_prompt, request: { path, name, ticket, task_type, profile } | null }] }

const fs = require("fs");
const path = require("path");

const GROUPINGS = ["day", "ticket", "recent"];
const GROUPING_LABELS = {
  day: "By day",
  ticket: "By ticket",
  recent: "Recent sessions",
};
const ROOT_KEY = "(work root)";

// Does a session match the search box? Every word must appear somewhere in its title,
// prompts, id, or its request's name, ticket, task type, profile or folder.
function matches(s, filter) {
  const words = (filter || "").toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const r = s.request || {};
  const hay = [s.title, s.first_prompt, s.last_prompt, s.id, r.name, r.ticket, r.task_type,
               r.profile, r.path].filter(Boolean).join("\n").toLowerCase();
  return words.every(w => hay.includes(w));
}

// Sessions worth listing: in the work root or assigned to a request, not empty (opened
// and closed without a prompt), and matching the search box.
function visible(data, { showEmpty = false, filter = "" } = {}) {
  return data.sessions.filter(s => (s.in_work_root || s.request) &&
    (showEmpty || s.title || s.first_prompt || s.last_prompt) && matches(s, filter));
}

// Requests, newest activity first, each with its sessions newest first. Sessions with no
// request (run in the work root itself) share one pseudo-request.
function requests(data, opts) {
  const byPath = new Map();
  for (const s of visible(data, opts)) {
    const key = s.request ? s.request.path : ROOT_KEY;
    if (!byPath.has(key)) {
      byPath.set(key, s.request
        ? { ...s.request, root: false, sessions: [] }
        : { path: data.work_root, name: "Work root — no request folder", ticket: "",
            task_type: "", profile: "", root: true, sessions: [] });
    }
    byPath.get(key).sessions.push(s);
  }
  const out = [...byPath.values()];
  for (const r of out) {
    r.sessions.sort((a, b) => b.mtime - a.mtime);
    r.mtime = r.sessions[0].mtime;
  }
  return out.sort((a, b) => b.mtime - a.mtime);
}

// YYYY-MM-DD from a request folder's YYYY/MM/DD/... path under the work root.
function dayOf(request, workRoot) {
  if (request.root) return ROOT_KEY;
  const rel = path.relative(workRoot, request.path).split(path.sep);
  if (rel.length >= 3 && /^\d{4}$/.test(rel[0])) return rel.slice(0, 3).join("-");
  return "(elsewhere)";
}

// Top level of the tree for a grouping: groups of requests, or (recent) sessions directly.
function tree(data, grouping, opts) {
  if (grouping === "recent") {
    const reqs = requests(data, opts);
    const reqOf = new Map();
    for (const r of reqs) for (const s of r.sessions) reqOf.set(s.id, r);
    return visible(data, opts).sort((a, b) => b.mtime - a.mtime)
      .map(s => ({ kind: "session", session: s, request: reqOf.get(s.id), showRequest: true }));
  }
  const keyOf = grouping === "ticket"
    ? r => (r.root ? ROOT_KEY : r.ticket || "(no ticket)")
    : r => dayOf(r, data.work_root);
  const groups = new Map();
  for (const r of requests(data, opts)) {
    const k = keyOf(r);
    if (!groups.has(k)) groups.set(k, { kind: "group", key: k, requests: [], mtime: r.mtime });
    groups.get(k).requests.push(r);
  }
  return [...groups.values()];   // requests arrive newest first, so groups do too
}

// What a session is called: its auto-title, else its first prompt, else its id.
function sessionLabel(s) {
  return s.title || s.first_prompt || s.last_prompt || s.id.slice(0, 8);
}

// A tab's name: "TICKET · label", leaving out Other / no ticket.
function tabName(request, label) {
  const t = request && request.ticket;
  return (t && t !== "Other" ? t + " · " : "") + label;
}

function ago(mtime, now = Date.now() / 1000) {
  const s = Math.max(0, now - mtime);
  if (s < 3600) return Math.max(1, Math.round(s / 60)) + "m";
  if (s < 86400) return Math.round(s / 3600) + "h";
  return Math.round(s / 86400) + "d";
}

// Tabs started before their session existed ("new request", "new session in this request")
// are matched to the first new session that shows up for them:
//   pending: [{ key, kind: "new" | "request", dir, since, knownRequests: Set, knownSessions: Set }]
// A "request" tab takes a new session in its folder; a "new" tab takes a session in a request
// folder that did not exist when the tab opened. Returns [{ key, session, request }].
function matchPending(pending, data, taken) {
  const out = [];
  const used = new Set(taken);
  const reqs = requests(data, { showEmpty: true });
  for (const p of pending) {
    const candidates = [];
    for (const r of reqs) {
      if (r.root) continue;
      if (p.kind === "request" ? r.path !== p.dir : p.knownRequests.has(r.path)) continue;
      for (const s of r.sessions) {
        if (!used.has(s.id) && !p.knownSessions.has(s.id) && s.mtime >= p.since) {
          candidates.push({ s, r });
        }
      }
    }
    candidates.sort((a, b) => a.s.mtime - b.s.mtime);
    if (candidates.length) {
      const { s, r } = candidates[0];
      used.add(s.id);
      out.push({ key: p.key, session: s, request: r });
    }
  }
  return out;
}

// RFC 4180 CSV (claude-search --csv -) → array of objects keyed by the header row.
function parseCsv(text) {
  const rows = [];
  let row = [], field = "", quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') { field += '"'; i++; }
      else if (c === '"') quoted = false;
      else field += c;
    } else if (c === '"') quoted = true;
    else if (c === ",") { row.push(field); field = ""; }
    else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(field); rows.push(row); row = []; field = "";
    } else field += c;
  }
  if (field || row.length) { row.push(field); rows.push(row); }
  const [head, ...body] = rows.filter(r => r.length > 1 || r[0]);
  return head ? body.map(r => Object.fromEntries(head.map((h, i) => [h, r[i] ?? ""]))) : [];
}

// Task types to offer: those in use (most recent first), then the configured seeds.
function taskTypes(data, seeds = "") {
  const out = [];
  const add = t => { t = (t || "").trim(); if (t && !out.includes(t)) out.push(t); };
  for (const r of requests(data, { showEmpty: true })) add(r.task_type);
  for (const t of seeds.split(",")) add(t);
  return out;
}

// Set a task type in a request's .session.json, as claude-type does: for one session
// (session_types[id]) or, with no id, the folder's default. Returns [old, new].
function setTaskType(folder, sessionId, type) {
  const p = path.join(folder, ".session.json");
  const d = JSON.parse(fs.readFileSync(p, "utf8"));
  const per = d.session_types && typeof d.session_types === "object" ? d.session_types : {};
  const old = (sessionId && per[sessionId]) || d.task_type || "";
  if (sessionId) { per[sessionId] = type; d.session_types = per; } else d.task_type = type;
  fs.writeFileSync(p, JSON.stringify(d, null, 2));
  return [old, type];
}

// Skills in the given skills dirs: [{ name, description }] from each SKILL.md's frontmatter.
function readSkills(dirs) {
  const out = new Map();
  for (const dir of dirs) {
    let names = [];
    try { names = fs.readdirSync(dir); } catch { continue; }
    for (const n of names.sort()) {
      let text;
      try { text = fs.readFileSync(path.join(dir, n, "SKILL.md"), "utf8"); } catch { continue; }
      const fm = (text.match(/^---\n([\s\S]*?)\n---/) || [])[1] || "";
      const get = k => ((fm.match(new RegExp("^" + k + ":\\s*(.*)$", "m")) || [])[1] || "")
        .trim().replace(/^["']|["']$/g, "");
      const name = get("name") || n;
      if (!out.has(name)) out.set(name, { name, description: get("description") });
    }
  }
  return [...out.values()];
}

// claude-audit arguments for a period and view.
function auditArgs(period, detail, date) {
  const args = { today: ["--day"], week: ["--week"], lastweek: ["--week", date], month: ["--month"],
                 day: ["--day", date], weekof: ["--week", date] }[period] || [];
  return detail ? [...args, "--detail"] : args;
}

module.exports = { GROUPINGS, GROUPING_LABELS, ROOT_KEY, matches, visible, requests, dayOf, tree,
                   sessionLabel, tabName, ago, matchPending, parseCsv, taskTypes, setTaskType,
                   readSkills, auditArgs };
