// claude-worksessions for VS Code: a sidebar of requests and their Claude sessions, each
// session opened as a terminal tab in the editor area, in its own folder and profile, plus
// the terminal commands (claude-sessions, claude-search, claude-audit, claude-type, ...) and
// the skills in the Command Palette. The data comes from `claude-sessions -a --json`; the
// logic lives in model.js.

const vscode = require("vscode");
const cp = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");
const M = require("./model");

const HOME = os.homedir();

function config() {
  const out = {};
  try {
    const f = process.env.CWS_CONFIG || path.join(HOME, ".config/claude-worksessions/config.env");
    for (const line of fs.readFileSync(f, "utf8").split("\n")) {
      const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)=["']?([^"'#\n]*)["']?/);
      if (m) out[m[1]] = m[2].trim().replace(/\$\{?HOME\}?/g, HOME);
    }
  } catch {}
  return out;
}

function sessionsCommand() {
  const set = vscode.workspace.getConfiguration("claudeWorksessions").get("sessionsCommand");
  return set || path.join(HOME, ".local/bin/claude-sessions");
}

// claude-search, claude-audit, ... live next to claude-sessions
const binPath = name => path.join(path.dirname(sessionsCommand()), name);

function run(file, args) {
  return new Promise((resolve, reject) => {
    cp.execFile(file, args, { maxBuffer: 64 << 20 }, (err, stdout, stderr) => {
      if (err) return reject(new Error((stderr || err.message).trim()));
      resolve(stdout);
    });
  });
}

const loadData = () => run(sessionsCommand(), ["-a", "--json"]).then(JSON.parse);

const shq = s => "'" + String(s).replace(/'/g, "'\\''") + "'";

class Sidebar {
  constructor(context) {
    this.context = context;
    this.data = { work_root: config().CWS_WORK_ROOT || HOME, sessions: [] };
    this.grouping = context.globalState.get("grouping", "day");
    this.sort = context.globalState.get("sort", "activity");
    this.pins = { sessions: {}, requests: {} };
    this.filter = "";
    this.tabs = new Map();      // session id → terminal
    this.pending = [];          // tabs waiting for their session to appear
    this.wanted = new Map();    // terminal → name it should have
    this.emitter = new vscode.EventEmitter();
    this.onDidChangeTreeData = this.emitter.event;
    this.loading = null;
    this.again = false;
  }

  opts() {
    return { filter: this.filter, sort: this.sort, pins: this.pins,
             showEmpty: vscode.workspace.getConfiguration("claudeWorksessions").get("showEmptySessions", false) };
  }

  setFilter(text) {
    this.filter = text || "";
    this.emitter.fire();
    this.onChange && this.onChange();
  }

  counts() {
    return { shown: M.visible(this.data, this.opts()).length,
             total: M.visible(this.data, { ...this.opts(), filter: "" }).length };
  }

  // --- data ---------------------------------------------------------------------------
  async refresh() {
    if (this.loading) { this.again = true; return this.loading; }
    this.loading = (async () => {
      try {
        this.data = await loadData();
        this.pins = M.readPins(this.data.work_root);
        this.error = null;
      } catch (e) {
        this.error = e.message;
      }
      this.link();
      this.emitter.fire();
      this.onChange && this.onChange();
    })();
    await this.loading;
    this.loading = null;
    if (this.again) { this.again = false; return this.refresh(); }
  }

  find(id) { return this.data.sessions.find(s => s.id === id); }

  reloadPins() {
    this.pins = M.readPins(this.data.work_root);
    this.emitter.fire();
  }

  togglePin(el) {
    const now = el.kind === "request" ? M.togglePin(this.data.work_root, "request", el.request.path)
                                      : M.togglePin(this.data.work_root, "session", el.session.id);
    this.reloadPins();
    return now;
  }

  requestOf(id) {
    return M.requests(this.data, { showEmpty: true }).find(r => r.sessions.some(s => s.id === id));
  }

  // Pending tabs meet their sessions; every linked tab gets its current name.
  link() {
    for (const m of M.matchPending(this.pending, this.data, this.tabs.keys())) {
      const p = this.pending.find(x => x.key === m.key);
      this.pending = this.pending.filter(x => x !== p);
      this.tabs.set(m.session.id, p.terminal);
    }
    for (const [id, term] of this.tabs) {
      const r = this.requestOf(id), s = this.find(id);
      if (s) this.wanted.set(term, M.tabName(r && !r.root ? r : null, M.sessionLabel(s)));
    }
    this.rename();
    this.save();
  }

  // VS Code can only rename the active terminal, so names are applied as tabs get focus.
  rename() {
    const t = vscode.window.activeTerminal, want = t && this.wanted.get(t);
    if (want && t.name !== want) {
      vscode.commands.executeCommand("workbench.action.terminal.renameWithArg", { name: want })
        .then(() => this.save(), () => {});
    }
  }

  // Tabs survive a window reload; remember which is which by name.
  save() {
    const byName = {};
    for (const [id, t] of this.tabs) byName[t.name] = id;
    this.context.workspaceState.update("tabs", byName);
  }

  restore() {
    const byName = this.context.workspaceState.get("tabs", {});
    for (const t of vscode.window.terminals) if (byName[t.name]) this.tabs.set(byName[t.name], t);
  }

  closed(term) {
    for (const [id, t] of this.tabs) if (t === term) this.tabs.delete(id);
    this.pending = this.pending.filter(p => p.terminal !== term);
    this.wanted.delete(term);
    this.save();
    this.emitter.fire();
  }

  // The session in the focused tab, if it is one of ours.
  activeSession() {
    const t = vscode.window.activeTerminal;
    for (const [id, x] of this.tabs) if (x === t) return this.find(id);
    return undefined;
  }

  // --- tabs ---------------------------------------------------------------------------
  terminal(name, cwd, command, icon = "sparkle") {
    const taken = new Set(vscode.window.terminals.map(t => t.name));
    let unique = name, n = 2;
    while (taken.has(unique)) unique = `${name} (${n++})`;
    const t = vscode.window.createTerminal({
      name: unique, cwd: fs.existsSync(cwd) ? cwd : this.data.work_root,
      location: vscode.TerminalLocation.Editor, iconPath: new vscode.ThemeIcon(icon),
    });
    t.sendText(command);
    t.show();
    return t;
  }

  open(session, request = this.requestOf(session.id)) {
    const open = this.tabs.get(session.id);
    if (open && vscode.window.terminals.includes(open)) return open.show();
    const profile = request && request.profile ? `-p ${shq(request.profile)} ` : "";
    const t = this.terminal(M.tabName(request && !request.root ? request : null, M.sessionLabel(session)),
                            session.cwd, `claude-resume ${profile}--resume ${shq(session.id)}`);
    this.tabs.set(session.id, t);
    this.save();
    this.emitter.fire();
  }

  startPending(kind, dir, name, command) {
    const t = this.terminal(name, dir, command);
    this.pending.push({
      key: String(Date.now()) + Math.random(), kind, dir, terminal: t,
      since: Date.now() / 1000 - 5,
      knownRequests: new Set(M.requests(this.data, { showEmpty: true }).map(r => r.path)),
      knownSessions: new Set(this.data.sessions.map(s => s.id)),
    });
  }

  newRequest(args = "", name = "new request") {
    this.startPending("new", this.data.work_root, name, "claude-new" + (args ? " " + args : ""));
  }

  addSession(request) {
    const env = request.profile ? `CLAUDE_CONFIG_DIR="$HOME/.claude-${request.profile}" ` : "";
    this.startPending("request", request.path, M.tabName(request, request.name), env + "claude");
  }

  // --- tree ---------------------------------------------------------------------------
  getChildren(el) {
    const opts = this.opts();
    if (!el) {
      const top = M.tree(this.data, this.grouping, opts);
      const firstGroup = top.findIndex(x => x.kind !== "pinned");
      return top.map((x, i) => ({ ...x, first: i === firstGroup }));
    }
    const inPinned = !!el.inPinned;
    if (el.kind === "pinned") {
      return [...el.requests.map(r => ({ kind: "request", request: r, inPinned: true })),
              ...el.sessions.map(x => ({ kind: "session", session: x.session, request: x.request,
                                         showRequest: true, inPinned: true }))];
    }
    if (el.kind === "group") return el.requests.map(r => ({ kind: "request", request: r }));
    if (el.kind === "request") {
      const r = el.request, files = r.files || [];
      return [...r.sessions.map(s => ({ kind: "session", session: s, request: r, inPinned })),
              ...(files.length ? [{ kind: "files", request: r, inPinned }] : [])];
    }
    if (el.kind === "files" || el.kind === "dir") {
      const files = M.shownFiles(el.request.files, this.filter);
      return M.fileChildren(files, el.kind === "dir" ? el.prefix : "").map(x => ({ ...x, request: el.request, inPinned }));
    }
    return [];
  }

  isOpen(id) {
    const t = this.tabs.get(id);
    return !!t && vscode.window.terminals.includes(t);
  }

  getTreeItem(el) {
    const C = vscode.TreeItemCollapsibleState;
    const now = Date.now() / 1000;
    // While searching everything opens up; ids carry the search so that takes effect.
    const searching = !!this.filter;
    const idp = `${this.grouping}|${this.filter}|${el.inPinned ? "p|" : ""}`;
    if (el.kind === "pinned") {
      const n = el.requests.length + el.sessions.length;
      const it = new vscode.TreeItem("Pinned", C.Expanded);
      it.id = idp + "pinned";
      it.description = String(n);
      it.iconPath = new vscode.ThemeIcon("pinned");
      return it;
    }
    if (el.kind === "group") {
      const it = new vscode.TreeItem(el.key, el.first || searching ? C.Expanded : C.Collapsed);
      it.id = idp + "g|" + el.key;
      it.description = `${el.requests.length} request${el.requests.length > 1 ? "s" : ""}`;
      it.iconPath = new vscode.ThemeIcon(this.grouping === "ticket" ? "tag" : "calendar");
      return it;
    }
    if (el.kind === "request") {
      const r = el.request;
      const it = new vscode.TreeItem(r.name, searching ? C.Expanded : C.Collapsed);
      it.id = idp + "r|" + r.path;
      const pinnedReq = M.isPinnedRequest(this.pins, this.data.work_root, r);
      it.contextValue = r.root ? "root" : pinnedReq ? "request-pinned" : "request";
      it.description = [pinnedReq && !el.inPinned && "pinned", this.grouping !== "ticket" && r.ticket,
                        r.task_type, r.profile, M.ago(r.mtime, now)].filter(Boolean).join(" · ");
      it.iconPath = new vscode.ThemeIcon(r.sessions.some(s => this.isOpen(s.id)) ? "folder-active" : "folder");
      const md = new vscode.MarkdownString();
      md.appendMarkdown("**").appendText(r.name).appendMarkdown("**\n\n");
      for (const [k, v] of [["ticket", r.ticket], ["type", r.task_type], ["profile", r.profile],
                            ["sessions", String(r.sessions.length)], ["last activity", M.ago(r.mtime, now) + " ago"]]) {
        md.appendMarkdown(`${k}: `).appendText(v || "—").appendMarkdown("  \n");
      }
      md.appendMarkdown("\n").appendText(path.relative(this.data.work_root, r.path) || r.path);
      it.tooltip = md;
      return it;
    }
    if (el.kind === "files") {
      const r = el.request, n = r.files.length;
      const it = new vscode.TreeItem("Files", searching ? C.Expanded : C.Collapsed);
      it.id = idp + "f|" + r.path;
      it.description = `${n}${r.files_truncated ? "+" : ""}`;
      it.iconPath = new vscode.ThemeIcon("files");
      it.contextValue = "files";
      return it;
    }
    if (el.kind === "dir") {
      const it = new vscode.TreeItem(el.name, searching ? C.Expanded : C.Collapsed);
      it.id = idp + "d|" + el.request.path + "|" + el.prefix;
      it.resourceUri = vscode.Uri.file(path.join(el.request.path, el.prefix));
      it.iconPath = vscode.ThemeIcon.Folder;
      it.contextValue = "dir";
      return it;
    }
    if (el.kind === "file") {
      const uri = vscode.Uri.file(path.join(el.request.path, el.rel));
      const it = new vscode.TreeItem(uri, C.None);
      it.id = idp + "file|" + el.request.path + "|" + el.rel;
      it.iconPath = vscode.ThemeIcon.File;
      it.tooltip = el.rel;
      it.contextValue = /\.(md|markdown)$/i.test(el.rel) ? "file-md" : "file";
      it.command = { command: "claudeWorksessions.openFile", title: "Open", arguments: [el] };
      return it;
    }
    const s = el.session, r = el.request, open = this.isOpen(s.id);
    const it = new vscode.TreeItem(M.sessionLabel(s), C.None);
    it.id = idp + "s|" + s.id + (el.showRequest ? "|flat" : "");
    const pinnedSes = M.isPinnedSession(this.pins, s.id);
    it.contextValue = pinnedSes ? "session-pinned" : "session";
    it.description = (el.showRequest && r ? (r.ticket && !r.root ? r.ticket + " · " : "") + r.name + " · " : "") +
      M.ago(s.mtime, now);
    it.iconPath = open ? new vscode.ThemeIcon("terminal", new vscode.ThemeColor("charts.green"))
                       : new vscode.ThemeIcon(pinnedSes ? "pinned" : "comment-discussion");
    it.command = { command: "claudeWorksessions.open", title: "Open", arguments: [el] };
    const clip = t => (t || "—").replace(/\s+/g, " ").slice(0, 300);
    const md = new vscode.MarkdownString();
    md.appendMarkdown("**").appendText(s.title || "(no title yet)").appendMarkdown("**")
      .appendMarkdown(open ? " — *open in a tab*\n\n" : "\n\n");
    md.appendMarkdown("**Last prompt:** ").appendText(clip(s.last_prompt)).appendMarkdown("\n\n");
    md.appendMarkdown("**First prompt:** ").appendText(clip(s.first_prompt)).appendMarkdown("\n\n");
    md.appendText([r && !r.root ? r.ticket || "no ticket" : "no request", r && r.task_type, r && r.profile,
                   M.ago(s.mtime, now) + " ago"].filter(Boolean).join(" · ")).appendMarkdown("\n\n");
    const wrote = s.written || [];
    if (wrote.length) {
      const rel = f => (r && !r.root && f.startsWith(r.path + path.sep) ? path.relative(r.path, f)
                        : f.replace(os.homedir(), "~"));
      md.appendMarkdown("**Wrote:** ").appendText(wrote.slice(0, 8).map(rel).join(", ") +
        (wrote.length > 8 ? ` and ${wrote.length - 8} more` : "")).appendMarkdown("\n\n");
    }
    md.appendText(s.id);
    it.tooltip = md;
    return it;
  }
}

// --- the search box above the tree --------------------------------------------------------
// A tree view can't hold a text field, so the box is a tiny webview: typing filters the
// tree, Enter runs claude-search over everything the sessions contain.
class SearchBox {
  constructor(bar, onEnter) { this.bar = bar; this.onEnter = onEnter; }

  resolveWebviewView(view) {
    this.view = view;
    view.webview.options = { enableScripts: true };
    const nonce = crypto.randomBytes(16).toString("hex");
    view.webview.html = `<!DOCTYPE html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';">
<style>
  body { padding: 4px 8px 2px; margin: 0; }
  input { width: 100%; box-sizing: border-box; padding: 3px 6px; font: inherit;
          color: var(--vscode-input-foreground); background: var(--vscode-input-background);
          border: 1px solid var(--vscode-input-border, transparent); border-radius: 2px; outline: none; }
  input:focus { border-color: var(--vscode-focusBorder); }
  #hint { font-size: 11px; opacity: .75; padding: 3px 1px 0; min-height: 14px; }
</style></head><body>
<input id="q" type="search" placeholder="Filter sessions · Enter searches their contents" value="">
<div id="hint"></div>
<script nonce="${nonce}">
  const vscode = acquireVsCodeApi(), q = document.getElementById("q"), hint = document.getElementById("hint");
  q.value = (vscode.getState() || {}).q || "";
  const send = () => { vscode.setState({ q: q.value }); vscode.postMessage({ type: "filter", value: q.value }); };
  q.addEventListener("input", send);
  q.addEventListener("keydown", e => {
    if (e.key === "Enter" && q.value.trim()) vscode.postMessage({ type: "search", value: q.value.trim() });
    if (e.key === "Escape") { q.value = ""; send(); }
  });
  window.addEventListener("message", e => {
    if (e.data.type === "hint") hint.textContent = e.data.text;
    if (e.data.type === "set") { q.value = e.data.value; send(); }
    if (e.data.type === "focus") q.focus();
  });
  send();
</script></body></html>`;
    view.webview.onDidReceiveMessage(m => {
      if (m.type === "filter") this.bar.setFilter(m.value);
      if (m.type === "search") this.onEnter(m.value);
    });
    this.update();
  }

  update() {
    if (!this.view) return;
    const { shown, total } = this.bar.counts();
    const text = this.bar.filter ? `${shown} of ${total} sessions · Enter to search contents` : "";
    this.view.webview.postMessage({ type: "hint", text });
  }

  clear() { this.view && this.view.webview.postMessage({ type: "set", value: "" }); }
  focus() { this.view && this.view.webview.postMessage({ type: "focus" }); }
}

// --- palette commands ------------------------------------------------------------------------
function sessionPicks(bar, sessions) {
  const now = Date.now() / 1000;
  return sessions.map(s => {
    const r = bar.requestOf(s.id);
    return {
      label: M.sessionLabel(s),
      description: [r && !r.root && r.ticket, r && (r.root ? "work root" : r.name), M.ago(s.mtime, now)]
        .filter(Boolean).join(" · "),
      detail: s.last_prompt ? "last: " + s.last_prompt.replace(/\s+/g, " ").slice(0, 160) : undefined,
      session: s,
    };
  });
}

async function pickSession(bar, placeHolder) {
  const pick = await vscode.window.showQuickPick(sessionPicks(bar, M.visible(bar.data, { showEmpty: false })),
                                                 { placeHolder, matchOnDescription: true, matchOnDetail: true });
  return pick && pick.session;
}

async function searchSessions(bar, query, ai = false) {
  query = query || await vscode.window.showInputBox({
    prompt: ai ? "Search sessions — Claude reads the best candidates and keeps the relevant ones"
               : "Search sessions: a ticket (BTPA-123) and/or any words",
    placeHolder: "BTPA-7959 firewall" });
  if (!query) return;
  const args = [...query.split(/\s+/).filter(Boolean), "--csv", "-", "--no-pick", "--limit", "25"];
  if (ai) args.push("--ai");
  let rows;
  try {
    rows = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: `claude-search ${query}${ai ? " --ai" : ""}` },
      () => run(binPath("claude-search"), args).then(M.parseCsv));
  } catch (e) {
    return vscode.window.showErrorMessage("claude-search failed: " + e.message);
  }
  if (!rows.length) return vscode.window.showInformationMessage(`No sessions match "${query}".`);
  const pick = await vscode.window.showQuickPick(rows.map(r => ({
    label: r.title || r.session_id.slice(0, 8),
    description: [r.level, r.ticket || r.task, path.basename(r.folder || ""), (r.start || "").slice(0, 10)]
      .filter(Boolean).join(" · "),
    detail: [r.why, r.snippet].filter(Boolean).join(" — "),
    row: r,
  })), { placeHolder: `${rows.length} session(s) for "${query}" — pick one to open`,
         matchOnDescription: true, matchOnDetail: true });
  if (!pick) return;
  const s = bar.find(pick.row.session_id);
  if (s) return bar.open(s);
  bar.terminal(pick.label, bar.data.work_root, pick.row.resume);   // not in the list (e.g. outside the root)
}

const PERIODS = [
  { label: "Today", period: "today" },
  { label: "This week", period: "week" },
  { label: "Last week", period: "lastweek" },
  { label: "This month", period: "month" },
  { label: "A day…", period: "day", ask: true },
  { label: "The week of a day…", period: "weekof", ask: true },
];

async function audit(bar) {
  const p = await vscode.window.showQuickPick(PERIODS, { placeHolder: "claude-audit — which period?" });
  if (!p) return;
  let date = "";
  if (p.period === "lastweek") date = new Date(Date.now() - 7 * 864e5).toISOString().slice(0, 10);
  if (p.ask) {
    date = await vscode.window.showInputBox({
      prompt: "Date (YYYY-MM-DD)", value: new Date().toISOString().slice(0, 10),
      validateInput: v => (/^\d{4}-\d{2}-\d{2}$/.test(v) ? null : "YYYY-MM-DD") });
    if (!date) return;
  }
  const view = await vscode.window.showQuickPick([
    { label: "Summary", description: "the weekly tracker rows", detail: false },
    { label: "Detail", description: "every session, meeting, email and chat", detail: true },
  ], { placeHolder: "Summary or every activity?" });
  if (!view) return;
  const args = M.auditArgs(p.period, view.detail, date);
  bar.terminal(`audit · ${p.label.replace("…", "")}${date ? " " + date : ""}${view.detail ? " · detail" : ""}`,
               bar.data.work_root, ["claude-audit", ...args.map(a => (a.startsWith("-") ? a : shq(a)))].join(" "),
               "graph");
}

async function setType(bar, el) {
  let folder, sessionId, current;
  if (el && el.kind === "request") {
    folder = el.request.path; current = el.request.task_type;
  } else {
    const s = (el && el.session) || bar.activeSession() || await pickSession(bar, "Set the task type of which session?");
    if (!s) return;
    const r = bar.requestOf(s.id);
    if (!r || r.root) return vscode.window.showWarningMessage("That session has no request folder to record a type in.");
    folder = r.path; sessionId = s.id; current = r.task_type;
  }
  if (!fs.existsSync(path.join(folder, ".session.json"))) {
    return vscode.window.showWarningMessage(`No .session.json in ${path.basename(folder)}.`);
  }
  const types = M.taskTypes(bar.data, config().CWS_TASK_TYPES || "");
  const qp = vscode.window.createQuickPick();
  qp.placeholder = `Task type ${sessionId ? "for this session" : "for the request (its default)"} — now: ${current || "none"}`;
  qp.items = types.map(t => ({ label: t, description: t === current ? "current" : "" }));
  const chosen = await new Promise(resolve => {
    qp.onDidAccept(() => resolve((qp.selectedItems[0] && qp.selectedItems[0].label) || qp.value.trim()));
    qp.onDidHide(() => resolve(undefined));
    qp.show();
  });
  qp.dispose();
  if (!chosen) return;
  const [old] = M.setTaskType(folder, sessionId, chosen);
  vscode.window.showInformationMessage(`Task type (${sessionId ? "session " + sessionId.slice(0, 8) : "request"}): ` +
                                       `${old || "none"} → ${chosen}`);
  bar.refresh();
}

async function goToRequest(bar) {
  const now = Date.now() / 1000;
  const reqs = M.requests(bar.data, { showEmpty: false }).filter(r => !r.root);
  const pick = await vscode.window.showQuickPick(reqs.map(r => ({
    label: r.name, description: [r.ticket, r.task_type, M.ago(r.mtime, now)].filter(Boolean).join(" · "),
    detail: path.relative(bar.data.work_root, r.path), request: r,
  })), { placeHolder: "Go to a request", matchOnDescription: true, matchOnDetail: true });
  if (!pick) return;
  const how = await vscode.window.showQuickPick([
    { label: "Open in a new window", how: "window" },
    { label: "Reveal in Explorer", how: "explorer" },
    { label: "New session in it", how: "session" },
  ], { placeHolder: pick.label });
  if (!how) return;
  if (how.how === "window") openInWindow(pick.request);
  if (how.how === "explorer") vscode.commands.executeCommand("revealInExplorer", vscode.Uri.file(pick.request.path));
  if (how.how === "session") bar.addSession(pick.request);
}

const openInWindow = r => vscode.commands.executeCommand("vscode.openFolder", vscode.Uri.file(r.path),
                                                         { forceNewWindow: true });

function skillDirs() {
  const conf = config();
  const profiles = (conf.CWS_PROFILES || "personal").split(/\s+/).filter(Boolean);
  const shared = conf.CWS_SHARED_PROFILE || profiles[0];
  return [shared, ...profiles].map(p => path.join(HOME, ".claude-" + p, "skills"));
}

async function runSkill(bar) {
  const skills = M.readSkills(skillDirs());
  if (!skills.length) return vscode.window.showInformationMessage("No skills found in ~/.claude-*/skills.");
  const pick = await vscode.window.showQuickPick(skills.map(s => ({ label: "/" + s.name, detail: s.description, skill: s })),
                                                 { placeHolder: "Run a skill — it starts a new request", matchOnDetail: true });
  if (!pick) return;
  const name = pick.skill.name.replace(/-/g, " ");
  bar.newRequest(`--prompt ${shq("/" + pick.skill.name)} ${shq(name)}`, "new request · /" + pick.skill.name);
}

// The Markdown file a Copy for email click means: a sidebar file, a URI from a menu, the
// active editor, or — from a Markdown preview, which passes nothing — the open document
// its tab is named after ("Preview notes.md").
function markdownTarget(arg) {
  if (arg && arg.request && arg.rel) return path.join(arg.request.path, arg.rel);
  if (arg && arg.fsPath) return arg.fsPath;
  const ed = vscode.window.activeTextEditor;
  if (ed && ed.document.languageId === "markdown") return ed.document.uri.fsPath;
  const tab = vscode.window.tabGroups && vscode.window.tabGroups.activeTabGroup.activeTab;
  const shown = tab && (tab.label || "").replace(/^\[?Preview\]?\s*/, "");
  const docs = vscode.workspace.textDocuments.filter(d => d.languageId === "markdown" && path.basename(d.uri.fsPath) === shown);
  return docs.length === 1 ? docs[0].uri.fsPath : undefined;
}

async function copyForEmail(arg) {
  const file = markdownTarget(arg);
  if (!file) return vscode.window.showWarningMessage("Open or select a Markdown file to copy for email.");
  const doc = vscode.workspace.textDocuments.find(d => d.uri.fsPath === file);
  if (doc && doc.isDirty) await doc.save();
  try {
    await run(binPath("claude-md-email"), [file]);
    vscode.window.showInformationMessage(`Copied ${path.basename(file)} for email — paste it into Outlook.`);
  } catch (e) {
    vscode.window.showErrorMessage(e.message);
  }
}

async function resumeById(bar) {
  const id = await vscode.window.showInputBox({ prompt: "Session id to resume",
    validateInput: v => (/^[0-9A-Za-z-]{2,}$/.test(v.trim()) ? null : "a session id, e.g. 34e66495-1e97-…") });
  if (!id) return;
  const s = bar.find(id.trim());
  if (s) return bar.open(s);
  bar.terminal(id.trim().slice(0, 8), bar.data.work_root, `claude-resume --resume ${shq(id.trim())}`);
}

function activate(context) {
  const bar = new Sidebar(context);
  bar.restore();
  const view = vscode.window.createTreeView("claudeWorksessions.sessions", { treeDataProvider: bar });
  const box = new SearchBox(bar, q => searchSessions(bar, q));
  bar.onChange = () => {
    view.description = `${M.GROUPING_LABELS[bar.grouping]} · ${M.SORT_LABELS[bar.sort] || M.SORT_LABELS.activity}`;
    view.message = bar.error ? `claude-sessions failed: ${bar.error}`
      : (bar.filter && !bar.counts().shown ? `No session matches "${bar.filter}" — press Enter in the box to search their contents.` : undefined);
    vscode.commands.executeCommand("setContext", "claudeWorksessions.filtering", !!bar.filter);
    box.update();
  };
  bar.onChange();

  const cmd = (name, fn) => vscode.commands.registerCommand("claudeWorksessions." + name, fn);
  context.subscriptions.push(
    view,
    vscode.window.registerWebviewViewProvider("claudeWorksessions.search", box),
    cmd("refresh", () => bar.refresh()),
    cmd("grouping", async () => {
      const pick = await vscode.window.showQuickPick(
        M.GROUPINGS.map(g => ({ label: M.GROUPING_LABELS[g], g, description: g === bar.grouping ? "current" : "" })),
        { placeHolder: "Group sessions" });
      if (!pick) return;
      bar.grouping = pick.g;
      context.globalState.update("grouping", pick.g);
      bar.emitter.fire();
      bar.onChange();
    }),
    cmd("sort", async () => {
      const pick = await vscode.window.showQuickPick(
        M.SORTS.map(k => ({ label: M.SORT_LABELS[k], k, description: k === bar.sort ? "current" : "" })),
        { placeHolder: "Sort sessions and requests (days stay newest first)" });
      if (!pick) return;
      bar.sort = pick.k;
      context.globalState.update("sort", pick.k);
      bar.emitter.fire();
      bar.onChange();
    }),
    cmd("newRequest", () => bar.newRequest()),
    cmd("open", el => bar.open(el.session, el.request)),
    cmd("addSession", el => bar.addSession(el.request)),
    cmd("reveal", el => vscode.commands.executeCommand("revealInExplorer", vscode.Uri.file(el.request.path))),
    cmd("revealInOS", el => vscode.commands.executeCommand("revealFileInOS", vscode.Uri.file(el.request.path))),
    cmd("openInWindow", el => openInWindow(el.request)),
    cmd("copyId", el => vscode.env.clipboard.writeText(el.session.id)),
    cmd("copyForEmail", arg => copyForEmail(arg)),
    cmd("pin", el => bar.togglePin(el)),
    cmd("unpin", el => bar.togglePin(el)),
    cmd("openFile", el => {
      const uri = vscode.Uri.file(path.join(el.request.path, el.rel));
      return vscode.commands.executeCommand(/\.(md|markdown)$/i.test(el.rel) ? "markdown.showPreview" : "vscode.open", uri);
    }),
    cmd("revealFile", el => vscode.commands.executeCommand("revealFileInOS",
      vscode.Uri.file(path.join(el.request.path, el.rel || el.prefix || "")))),
    cmd("copyPath", el => vscode.env.clipboard.writeText(path.join(el.request.path, el.rel || el.prefix || ""))),
    cmd("recentSessions", async () => { const s = await pickSession(bar, "Recent sessions — pick one to open"); if (s) bar.open(s); }),
    cmd("search", () => searchSessions(bar)),
    cmd("searchAi", () => searchSessions(bar, undefined, true)),
    cmd("audit", () => audit(bar)),
    cmd("setType", el => setType(bar, el)),
    cmd("goToRequest", () => goToRequest(bar)),
    cmd("runSkill", () => runSkill(bar)),
    cmd("resumeById", () => resumeById(bar)),
    cmd("focusSearch", async () => { await vscode.commands.executeCommand("claudeWorksessions.search.focus"); box.focus(); }),
    cmd("clearFilter", () => { box.clear(); bar.setFilter(""); }),
    vscode.window.onDidCloseTerminal(t => bar.closed(t)),
    vscode.window.onDidChangeActiveTerminal(() => bar.rename()),
    vscode.workspace.onDidChangeConfiguration(e => {
      if (e.affectsConfiguration("claudeWorksessions")) bar.refresh();
    }),
  );

  // Transcripts and .session.json files change as sessions run: refresh shortly after.
  let timer;
  const soon = () => { clearTimeout(timer); timer = setTimeout(() => bar.refresh(), 1500); };
  const conf = config();
  const shared = conf.CWS_SHARED_PROFILE || (conf.CWS_PROFILES || "personal").split(/\s+/)[0];
  let projects = path.join(HOME, ".claude-" + shared, "projects");
  try { projects = fs.realpathSync(projects); } catch {}
  // request folders: .session.json edits, and files added or removed (the Files entries)
  for (const [dir, glob] of [[projects, "**/*.jsonl"], [bar.data.work_root, "[0-9]*/*/*/*/**"]]) {
    const w = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(vscode.Uri.file(dir), glob));
    w.onDidChange(soon); w.onDidCreate(soon); w.onDidDelete(soon);
    context.subscriptions.push(w);
  }
  context.subscriptions.push({ dispose: () => clearTimeout(timer) });
  // pins change here or on another machine (the work root syncs)
  const pinWatch = vscode.workspace.createFileSystemWatcher(
    new vscode.RelativePattern(vscode.Uri.file(bar.data.work_root), "_config/pinned.json"));
  pinWatch.onDidChange(() => bar.reloadPins()); pinWatch.onDidCreate(() => bar.reloadPins());
  pinWatch.onDidDelete(() => bar.reloadPins());
  context.subscriptions.push(pinWatch);
  bar.refresh();
}

module.exports = { activate, deactivate() {} };
