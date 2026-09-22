// PROTOTYPE — throwaway. Answers one question: does a sidebar of requests/sessions, each
// session opened as a terminal tab, feel like the right way to work in VS Code?
// No tests, no error handling to speak of, nothing persisted.

const vscode = require("vscode");
const fs = require("fs");
const os = require("os");
const path = require("path");

const HOME = os.homedir();
const PROJECTS = fs.realpathSync(path.join(HOME, ".claude", "projects")); // ~/.claude → the shared profile

function workRoot() {
  try {
    const conf = fs.readFileSync(path.join(HOME, ".config/claude-worksessions/config.env"), "utf8");
    const m = conf.match(/^CWS_WORK_ROOT="?([^"\n]+)"?/m);
    if (m) return m[1].replace(/\$\{?HOME\}?/g, HOME);
  } catch {}
  return path.join(HOME, "work_sessions");
}
const ROOT = workRoot();

function movedFolders() {
  try { return JSON.parse(fs.readFileSync(path.join(ROOT, "_audit/moved-folders.json"), "utf8")); }
  catch { return {}; }
}

// --- transcripts ------------------------------------------------------------------------
// Only lines we need are parsed: the first with a cwd, the first real prompt, and the
// latest ai-title / last-prompt. Cached by mtime+size so a refresh re-reads changed files only.
const cache = new Map();

function firstText(content) {
  const t = typeof content === "string" ? content
    : (Array.isArray(content) ? (content.find(b => b && b.type === "text") || {}).text : null);
  if (!t || t.startsWith("<") || !t.trim()) return null;
  return t.trim().split("\n")[0];
}

function readTranscript(file) {
  const st = fs.statSync(file);
  const key = st.mtimeMs + ":" + st.size;
  const hit = cache.get(file);
  if (hit && hit.key === key) return hit.value;
  const v = { id: path.basename(file, ".jsonl"), cwd: null, title: null, lastPrompt: null,
              firstPrompt: null, mtime: st.mtime };
  for (const line of fs.readFileSync(file, "utf8").split("\n")) {
    const want = (!v.cwd && line.includes('"cwd"')) || line.includes('"ai-title"')
      || line.includes('"last-prompt"') || (!v.firstPrompt && line.includes('"type":"user"'));
    if (!want) continue;
    let m; try { m = JSON.parse(line); } catch { continue; }
    if (!m || typeof m !== "object") continue;
    if (!v.cwd && m.cwd) v.cwd = m.cwd;
    if (m.type === "ai-title" && m.aiTitle) v.title = m.aiTitle;
    if (m.type === "last-prompt" && m.lastPrompt) v.lastPrompt = m.lastPrompt;
    if (m.type === "user" && !v.firstPrompt && m.message) v.firstPrompt = firstText(m.message.content);
  }
  cache.set(file, { key, value: v });
  return v;
}

function requestMeta(dir) {
  try { return JSON.parse(fs.readFileSync(path.join(dir, ".session.json"), "utf8")); }
  catch { return null; }
}

// Sessions under the work root, one per id (a moved folder leaves a copy behind), newest first.
function loadSessions() {
  const moved = movedFolders();
  const byId = new Map();
  let dirs = [];
  try { dirs = fs.readdirSync(PROJECTS); } catch {}
  for (const d of dirs) {
    let files = [];
    try { files = fs.readdirSync(path.join(PROJECTS, d)).filter(f => f.endsWith(".jsonl")); } catch { continue; }
    for (const f of files) {
      let s; try { s = readTranscript(path.join(PROJECTS, d, f)); } catch { continue; }
      if (!s.cwd || !(s.cwd + "/").startsWith(ROOT + "/")) continue;
      let cwd = s.cwd;
      for (const [from, to] of Object.entries(moved)) {
        if (cwd === from || cwd.startsWith(from + "/")) { cwd = to + cwd.slice(from.length); break; }
      }
      const prev = byId.get(s.id);
      if (!prev || prev.mtime < s.mtime) byId.set(s.id, { ...s, cwd });
    }
  }
  return [...byId.values()].sort((a, b) => b.mtime - a.mtime);
}

// A session's request folder: YYYY/MM/DD/HH-mm-ss_slug under the root, or the root itself.
function requestOf(cwd) {
  const rel = path.relative(ROOT, cwd).split(path.sep);
  if (rel.length >= 4 && /^\d{4}$/.test(rel[0])) return path.join(ROOT, ...rel.slice(0, 4));
  return ROOT;
}

// --- tree ---------------------------------------------------------------------------------
const GROUPINGS = ["day", "ticket", "recent"];
const GROUP_LABEL = { day: "Day → request → session", ticket: "Ticket → request → session",
                      recent: "Recent sessions (flat)" };

function ago(d) {
  const s = (Date.now() - d) / 1000;
  if (s < 3600) return Math.max(1, Math.round(s / 60)) + "m";
  if (s < 86400) return Math.round(s / 3600) + "h";
  return Math.round(s / 86400) + "d";
}

class Provider {
  constructor(tabs) {
    this.tabs = tabs;
    this.grouping = "day";
    this._emitter = new vscode.EventEmitter();
    this.onDidChangeTreeData = this._emitter.event;
    this.reload();
  }
  reload() {
    const t0 = Date.now();
    this.sessions = loadSessions();
    this.requests = new Map();
    for (const s of this.sessions) {
      const dir = requestOf(s.cwd);
      if (!this.requests.has(dir)) {
        const meta = dir === ROOT ? null : requestMeta(dir);
        this.requests.set(dir, { dir, meta, sessions: [],
          name: meta?.name || (dir === ROOT ? "(work root — no request folder)" : path.basename(dir)) });
      }
      this.requests.get(dir).sessions.push(s);
    }
    this.loadMs = Date.now() - t0;
    this._emitter.fire();
  }
  refreshView() { this._emitter.fire(); }

  getChildren(el) {
    if (!el) {
      const reqs = [...this.requests.values()];
      if (this.grouping === "recent") return this.sessions.map(s => ({ kind: "session", s, showReq: true }));
      const keyOf = this.grouping === "day"
        ? r => r.dir === ROOT ? "(work root)" : path.relative(ROOT, r.dir).split(path.sep).slice(0, 3).join("-")
        : r => r.meta?.ticket || "(no ticket)";
      const groups = new Map();
      for (const r of reqs) {
        const k = keyOf(r);
        if (!groups.has(k)) groups.set(k, { kind: "group", key: k, reqs: [], latest: 0 });
        const g = groups.get(k);
        g.reqs.push(r);
        g.latest = Math.max(g.latest, r.sessions[0].mtime);
      }
      return [...groups.values()].sort((a, b) => b.latest - a.latest).map((g, i) => ({ ...g, first: i === 0 }));
    }
    if (el.kind === "group") return el.reqs.map(r => ({ kind: "request", r }));
    if (el.kind === "request") return el.r.sessions.map(s => ({ kind: "session", s }));
    return [];
  }

  getTreeItem(el) {
    const C = vscode.TreeItemCollapsibleState;
    if (el.kind === "group") {
      const it = new vscode.TreeItem(el.key, el.first ? C.Expanded : C.Collapsed);
      it.description = el.reqs.length + " request" + (el.reqs.length > 1 ? "s" : "");
      it.iconPath = new vscode.ThemeIcon(this.grouping === "day" ? "calendar" : "tag");
      return it;
    }
    if (el.kind === "request") {
      const r = el.r, m = r.meta || {};
      const it = new vscode.TreeItem(r.name, C.Collapsed);
      it.contextValue = r.dir === ROOT ? "root" : "request";
      it.description = [this.grouping !== "ticket" && m.ticket, m.task_type, m.profile].filter(Boolean).join(" · ");
      it.iconPath = new vscode.ThemeIcon(r.sessions.some(s => this.tabs.has(s.id)) ? "folder-active" : "folder");
      it.tooltip = new vscode.MarkdownString(
        `**${r.name}**\n\n` +
        `| | |\n|---|---|\n| ticket | ${m.ticket || "—"} |\n| type | ${m.task_type || "—"} |\n` +
        `| profile | ${m.profile || "—"} |\n| sessions | ${r.sessions.length} |\n| last activity | ${ago(r.sessions[0].mtime)} ago |\n\n` +
        "`" + path.relative(ROOT, r.dir) + "`");
      return it;
    }
    const s = el.s, open = this.tabs.has(s.id);
    const req = this.requests.get(requestOf(s.cwd)), m = req.meta || {};
    const it = new vscode.TreeItem(s.title || s.firstPrompt || s.id.slice(0, 8), C.None);
    it.contextValue = open ? "session-open" : "session";
    it.description = (el.showReq ? (m.ticket ? m.ticket + " · " : "") + req.name + " · " : "") + ago(s.mtime);
    it.iconPath = new vscode.ThemeIcon(open ? "terminal" : "comment-discussion",
      open ? new vscode.ThemeColor("charts.green") : undefined);
    it.command = { command: "cwsProto.open", title: "Open", arguments: [el] };
    const q = t => (t || "—").replace(/\n/g, " ").slice(0, 300);
    it.tooltip = new vscode.MarkdownString(
      `**${s.title || "(no title yet)"}**${open ? "  — *open in a tab*" : ""}\n\n` +
      `**Last prompt:** ${q(s.lastPrompt)}\n\n**First prompt:** ${q(s.firstPrompt)}\n\n` +
      `${m.ticket || "no ticket"} · ${m.task_type || "no type"} · ${m.profile || "default profile"} · ${ago(s.mtime)} ago\n\n` +
      "`" + s.id + "`");
    return it;
  }
}

// --- tabs -----------------------------------------------------------------------------------
function activate(context) {
  const tabs = new Map(); // session id → terminal (in-memory: lost on reload, fine for a prototype)
  const provider = new Provider(tabs);
  const view = vscode.window.createTreeView("cwsProto.tree", { treeDataProvider: provider });
  const setMessage = () => {
    view.message = `PROTOTYPE · ${GROUP_LABEL[provider.grouping]} · ${provider.sessions.length} sessions, ` +
      `${provider.requests.size} requests · scanned in ${provider.loadMs} ms`;
  };
  setMessage();

  const tab = (name, cwd, cmd) => {
    const t = vscode.window.createTerminal({ name, cwd, location: vscode.TerminalLocation.Editor,
                                             iconPath: new vscode.ThemeIcon("sparkle") });
    t.sendText(cmd);
    t.show();
    return t;
  };
  const tabName = (s, meta) => ((meta?.ticket && meta.ticket !== "Other") ? meta.ticket + " · " : "") +
    (s?.title || meta?.name || "new session");

  context.subscriptions.push(
    view,
    vscode.window.onDidCloseTerminal(t => {
      for (const [id, x] of tabs) if (x === t) tabs.delete(id);
      provider.refreshView();
    }),
    vscode.commands.registerCommand("cwsProto.refresh", () => { provider.reload(); setMessage(); }),
    vscode.commands.registerCommand("cwsProto.grouping", async () => {
      const pick = await vscode.window.showQuickPick(
        GROUPINGS.map(g => ({ label: GROUP_LABEL[g], g, description: g === provider.grouping ? "current" : "" })),
        { placeHolder: "Group the sessions by…" });
      if (pick) { provider.grouping = pick.g; provider.refreshView(); setMessage(); }
    }),
    vscode.commands.registerCommand("cwsProto.newSession", () => tab("new request", ROOT, "claude-new")),
    vscode.commands.registerCommand("cwsProto.open", el => {
      const s = el.s, open = tabs.get(s.id);
      if (open) { open.show(); return; }
      const meta = requestMeta(requestOf(s.cwd));
      const profile = meta?.profile ? `-p ${meta.profile} ` : "";
      tabs.set(s.id, tab(tabName(s, meta), s.cwd, `claude-resume ${profile}--resume ${s.id}`));
      provider.refreshView();
    }),
    vscode.commands.registerCommand("cwsProto.addSession", el => {
      const m = el.r.meta || {};
      const cfg = m.profile ? `CLAUDE_CONFIG_DIR="$HOME/.claude-${m.profile}" ` : "";
      tab(tabName(null, m), el.r.dir, `${cfg}claude`);
    }),
    vscode.commands.registerCommand("cwsProto.reveal", el =>
      vscode.commands.executeCommand("revealInExplorer", vscode.Uri.file(el.r.dir))),
  );

  // Pick up new titles/prompts as sessions run: transcripts change → rescan (changed files only).
  let timer;
  const watcher = vscode.workspace.createFileSystemWatcher(
    new vscode.RelativePattern(vscode.Uri.file(PROJECTS), "**/*.jsonl"));
  const soon = () => { clearTimeout(timer); timer = setTimeout(() => { provider.reload(); setMessage(); }, 2000); };
  watcher.onDidChange(soon); watcher.onDidCreate(soon);
  context.subscriptions.push(watcher);
}

module.exports = { activate, deactivate() {} };
