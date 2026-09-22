// claude-worksessions for VS Code: a sidebar of requests and their Claude sessions, each
// session opened as a terminal tab in the editor area, in its own folder and profile.
// The data comes from `claude-sessions -a --json`; the logic lives in model.js.

const vscode = require("vscode");
const cp = require("child_process");
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

function loadData() {
  return new Promise((resolve, reject) => {
    cp.execFile(sessionsCommand(), ["-a", "--json"], { maxBuffer: 64 << 20 }, (err, stdout, stderr) => {
      if (err) return reject(new Error((stderr || err.message).trim()));
      try { resolve(JSON.parse(stdout)); } catch (e) { reject(e); }
    });
  });
}

const shq = s => "'" + String(s).replace(/'/g, "'\\''") + "'";

class Sidebar {
  constructor(context) {
    this.context = context;
    this.data = { work_root: config().CWS_WORK_ROOT || HOME, sessions: [] };
    this.grouping = context.globalState.get("grouping", "day");
    this.tabs = new Map();      // session id → terminal
    this.pending = [];          // tabs waiting for their session to appear
    this.wanted = new Map();    // terminal → name it should have
    this.emitter = new vscode.EventEmitter();
    this.onDidChangeTreeData = this.emitter.event;
    this.loading = null;
    this.again = false;
  }

  showEmpty() {
    return vscode.workspace.getConfiguration("claudeWorksessions").get("showEmptySessions", false);
  }

  // --- data ---------------------------------------------------------------------------
  async refresh() {
    if (this.loading) { this.again = true; return this.loading; }
    this.loading = (async () => {
      try {
        this.data = await loadData();
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

  // Pending tabs meet their sessions; every linked tab gets its current name.
  link() {
    for (const m of M.matchPending(this.pending, this.data, this.tabs.keys())) {
      const p = this.pending.find(x => x.key === m.key);
      this.pending = this.pending.filter(x => x !== p);
      this.tabs.set(m.session.id, p.terminal);
    }
    const reqs = M.requests(this.data, { showEmpty: true });
    for (const [id, term] of this.tabs) {
      const r = reqs.find(r => r.sessions.some(s => s.id === id));
      const s = this.find(id);
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

  // --- tabs ---------------------------------------------------------------------------
  terminal(name, cwd, command) {
    const taken = new Set(vscode.window.terminals.map(t => t.name));
    let unique = name, n = 2;
    while (taken.has(unique)) unique = `${name} (${n++})`;
    const t = vscode.window.createTerminal({
      name: unique, cwd: fs.existsSync(cwd) ? cwd : this.data.work_root,
      location: vscode.TerminalLocation.Editor, iconPath: new vscode.ThemeIcon("sparkle"),
    });
    t.sendText(command);
    t.show();
    return t;
  }

  open(session, request) {
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

  newRequest() {
    this.startPending("new", this.data.work_root, "new request", "claude-new");
  }

  addSession(request) {
    const env = request.profile ? `CLAUDE_CONFIG_DIR="$HOME/.claude-${request.profile}" ` : "";
    this.startPending("request", request.path, M.tabName(request, request.name), env + "claude");
  }

  // --- tree ---------------------------------------------------------------------------
  getChildren(el) {
    const opts = { showEmpty: this.showEmpty() };
    if (!el) return M.tree(this.data, this.grouping, opts).map((x, i) => ({ ...x, first: i === 0 }));
    if (el.kind === "group") return el.requests.map(r => ({ kind: "request", request: r }));
    if (el.kind === "request") {
      return el.request.sessions.map(s => ({ kind: "session", session: s, request: el.request }));
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
    if (el.kind === "group") {
      const it = new vscode.TreeItem(el.key, el.first ? C.Expanded : C.Collapsed);
      it.description = `${el.requests.length} request${el.requests.length > 1 ? "s" : ""}`;
      it.iconPath = new vscode.ThemeIcon(this.grouping === "ticket" ? "tag" : "calendar");
      return it;
    }
    if (el.kind === "request") {
      const r = el.request;
      const it = new vscode.TreeItem(r.name, C.Collapsed);
      it.contextValue = r.root ? "root" : "request";
      it.description = [this.grouping !== "ticket" && r.ticket, r.task_type, r.profile, M.ago(r.mtime, now)]
        .filter(Boolean).join(" · ");
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
    const s = el.session, r = el.request, open = this.isOpen(s.id);
    const it = new vscode.TreeItem(M.sessionLabel(s), C.None);
    it.contextValue = "session";
    it.description = (el.showRequest && r ? (r.ticket && !r.root ? r.ticket + " · " : "") + r.name + " · " : "") +
      M.ago(s.mtime, now);
    it.iconPath = open ? new vscode.ThemeIcon("terminal", new vscode.ThemeColor("charts.green"))
                       : new vscode.ThemeIcon("comment-discussion");
    it.command = { command: "claudeWorksessions.open", title: "Open", arguments: [el] };
    const clip = t => (t || "—").replace(/\s+/g, " ").slice(0, 300);
    const md = new vscode.MarkdownString();
    md.appendMarkdown("**").appendText(s.title || "(no title yet)").appendMarkdown("**")
      .appendMarkdown(open ? " — *open in a tab*\n\n" : "\n\n");
    md.appendMarkdown("**Last prompt:** ").appendText(clip(s.last_prompt)).appendMarkdown("\n\n");
    md.appendMarkdown("**First prompt:** ").appendText(clip(s.first_prompt)).appendMarkdown("\n\n");
    md.appendText([r && !r.root ? r.ticket || "no ticket" : "no request", r && r.task_type, r && r.profile,
                   M.ago(s.mtime, now) + " ago"].filter(Boolean).join(" · ")).appendMarkdown("\n\n");
    md.appendText(s.id);
    it.tooltip = md;
    return it;
  }
}

function activate(context) {
  const bar = new Sidebar(context);
  bar.restore();
  const view = vscode.window.createTreeView("claudeWorksessions.sessions", { treeDataProvider: bar });
  bar.onChange = () => {
    view.description = M.GROUPING_LABELS[bar.grouping];
    view.message = bar.error ? `claude-sessions failed: ${bar.error}` : undefined;
  };
  bar.onChange();

  const cmd = (name, fn) => vscode.commands.registerCommand("claudeWorksessions." + name, fn);
  context.subscriptions.push(
    view,
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
    cmd("newRequest", () => bar.newRequest()),
    cmd("open", el => bar.open(el.session, el.request)),
    cmd("addSession", el => bar.addSession(el.request)),
    cmd("reveal", el => vscode.commands.executeCommand("revealInExplorer", vscode.Uri.file(el.request.path))),
    cmd("revealInOS", el => vscode.commands.executeCommand("revealFileInOS", vscode.Uri.file(el.request.path))),
    cmd("copyId", el => vscode.env.clipboard.writeText(el.session.id)),
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
  for (const [dir, glob] of [[projects, "**/*.jsonl"], [bar.data.work_root, "*/*/*/*/.session.json"]]) {
    const w = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(vscode.Uri.file(dir), glob));
    w.onDidChange(soon); w.onDidCreate(soon); w.onDidDelete(soon);
    context.subscriptions.push(w);
  }
  context.subscriptions.push({ dispose: () => clearTimeout(timer) });
  bar.refresh();
}

module.exports = { activate, deactivate() {} };
