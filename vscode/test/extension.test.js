// extension.js against a fake vscode API: activates, loads data from a stub claude-sessions,
// renders every tree item in every grouping, and opens / links tabs.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const Module = require("module");

function fakeVscode(settings) {
  const commands = new Map(), executed = [], terminals = [], listeners = {};
  const on = name => fn => { (listeners[name] ||= []).push(fn); return { dispose() {} }; };
  class EventEmitter { constructor() { this.fns = []; this.event = f => this.fns.push(f); } fire() { this.fns.forEach(f => f()); } }
  class MarkdownString {
    constructor() { this.value = ""; }
    appendMarkdown(s) { this.value += s; return this; }
    appendText(s) { this.value += s; return this; }
  }
  const vscode = {
    EventEmitter, MarkdownString,
    TreeItem: class { constructor(label, state) { this.label = label; this.collapsibleState = state; } },
    TreeItemCollapsibleState: { None: 0, Collapsed: 1, Expanded: 2 },
    ThemeIcon: class { constructor(id, color) { this.id = id; this.color = color; } },
    ThemeColor: class { constructor(id) { this.id = id; } },
    TerminalLocation: { Panel: 1, Editor: 2 },
    RelativePattern: class { constructor(base, pattern) { this.base = base; this.pattern = pattern; } },
    Uri: { file: p => ({ fsPath: p }) },
    env: { clipboard: { writeText: async t => executed.push(["clipboard", t]) } },
    workspace: {
      getConfiguration: () => ({ get: (k, d) => (k in settings ? settings[k] : d) }),
      onDidChangeConfiguration: on("config"),
      createFileSystemWatcher: () => ({ onDidChange() {}, onDidCreate() {}, onDidDelete() {}, dispose() {} }),
    },
    window: {
      terminals, activeTerminal: undefined,
      createTreeView: (id, opts) => ({ id, provider: opts.treeDataProvider, dispose() {} }),
      createTerminal: opts => {
        const t = { ...opts, sent: [], sendText(s) { this.sent.push(s); }, show() { vscode.window.activeTerminal = this; } };
        terminals.push(t);
        return t;
      },
      showQuickPick: async items => items.find(i => i.g === "ticket"),
      onDidCloseTerminal: on("close"),
      onDidChangeActiveTerminal: on("active"),
    },
    commands: {
      registerCommand: (name, fn) => { commands.set(name, fn); return { dispose() {} }; },
      executeCommand: async (name, arg) => {
        executed.push([name, arg]);
        if (name === "workbench.action.terminal.renameWithArg") vscode.window.activeTerminal.name = arg.name;
      },
    },
  };
  return { vscode, commands, executed, terminals, listeners };
}

function load(fake) {
  const orig = Module._load;
  Module._load = function (req, ...rest) { return req === "vscode" ? fake.vscode : orig.call(this, req, ...rest); };
  try {
    delete require.cache[require.resolve("../extension")];
    return require("../extension");
  } finally { Module._load = orig; }
}

function context() {
  const store = new Map();
  const memento = () => ({ get: (k, d) => (store.has(k) ? store.get(k) : d), update: async (k, v) => store.set(k, v) });
  return { subscriptions: [], globalState: memento(), workspaceState: memento() };
}

function stubSessions(dir, data) {
  const json = path.join(dir, "data.json"), bin = path.join(dir, "claude-sessions");
  fs.writeFileSync(json, JSON.stringify(data));
  fs.writeFileSync(bin, `#!/bin/sh\ncat "${json}"\n`, { mode: 0o755 });
  return { bin, json };
}

// activate() starts a load; wait for it rather than for a fixed time
const settle = ctx => ctx.subscriptions[0].provider.loading;

function allItems(provider) {
  const out = [];
  const walk = el => {
    for (const c of provider.getChildren(el)) { out.push([c, provider.getTreeItem(c)]); walk(c); }
  };
  walk(undefined);
  return out;
}

test("activates, renders every grouping and opens sessions in tabs", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cws-ext-"));
  const root = path.join(dir, "ws");
  const A = { path: path.join(root, "2026/09/22/10-00-00_a"), name: "demo", ticket: "BTPA-1",
              task_type: "security", profile: "work" };
  fs.mkdirSync(A.path, { recursive: true });
  const now = Date.now() / 1000;
  const data = { work_root: root, sessions: [
    { id: "s1", mtime: now - 60, cwd: A.path, in_work_root: true, title: "Fix *the* job",
      first_prompt: "first", last_prompt: "last", request: A },
    { id: "s0", mtime: now - 7200, cwd: root, in_work_root: true, title: null,
      first_prompt: "in the root", last_prompt: null, request: null },
  ] };
  const { bin, json } = stubSessions(dir, data);
  const fake = fakeVscode({ sessionsCommand: bin });
  const ext = load(fake);
  const ctx = context();
  ext.activate(ctx);
  await settle(ctx);
  const view = ctx.subscriptions[0];
  const p = view.provider;
  assert.strictEqual(view.description, "By day");
  assert.strictEqual(view.message, undefined);

  let items = allItems(p);
  const labels = items.map(([, it]) => it.label);
  assert.deepStrictEqual(labels, ["2026-09-22", "demo", "Fix *the* job", "(work root)",
                                  "Work root — no request folder", "in the root"]);
  const [, s1] = items.find(([c]) => c.session && c.session.id === "s1");
  assert.match(s1.tooltip.value, /Fix \*the\* job/);
  assert.match(s1.tooltip.value, /BTPA-1 · security · work · 1m ago/);

  // open → a terminal tab running claude-resume with the profile; opening again reuses it
  await fake.commands.get("claudeWorksessions.open")(items.find(([c]) => c.session?.id === "s1")[0]);
  assert.strictEqual(fake.terminals.length, 1);
  const t = fake.terminals[0];
  assert.strictEqual(t.name, "BTPA-1 · Fix *the* job");
  assert.strictEqual(t.location, 2);
  assert.deepStrictEqual(t.sent, ["claude-resume -p 'work' --resume 's1'"]);
  await fake.commands.get("claudeWorksessions.open")(items.find(([c]) => c.session?.id === "s1")[0]);
  assert.strictEqual(fake.terminals.length, 1);
  items = allItems(p);
  assert.strictEqual(items.find(([c]) => c.session?.id === "s1")[1].iconPath.id, "terminal");
  assert.strictEqual(items.find(([c]) => c.kind === "request" && !c.request.root)[1].iconPath.id, "folder-active");

  // a root session opens with no profile and no ticket in its name
  await fake.commands.get("claudeWorksessions.open")(items.find(([c]) => c.session?.id === "s0")[0]);
  assert.deepStrictEqual(fake.terminals[1].sent, ["claude-resume --resume 's0'"]);
  assert.strictEqual(fake.terminals[1].name, "in the root");

  // grouping switch: remembered, recent shows the request next to each session
  await fake.commands.get("claudeWorksessions.grouping")();
  assert.strictEqual(ctx.globalState.get("grouping"), "ticket");
  assert.strictEqual(view.description, "By ticket");
  assert.deepStrictEqual(allItems(p).map(([, it]) => it.label)[0], "BTPA-1");
  p.grouping = "recent";
  assert.match(allItems(p)[0][1].description, /^BTPA-1 · demo · 1m$/);

  // new session in the request: pending until its transcript appears, then linked and renamed
  const reqEl = { kind: "request", request: { ...A, sessions: [] } };
  await fake.commands.get("claudeWorksessions.addSession")(reqEl);
  const nt = fake.terminals[2];
  assert.deepStrictEqual(nt.sent, ['CLAUDE_CONFIG_DIR="$HOME/.claude-work" claude']);
  assert.strictEqual(nt.name, "BTPA-1 · demo");
  data.sessions.push({ id: "s2", mtime: Date.now() / 1000, cwd: A.path, in_work_root: true,
                       title: "New work", first_prompt: "go", last_prompt: "go", request: A });
  fs.writeFileSync(json, JSON.stringify(data));
  await fake.commands.get("claudeWorksessions.refresh")();
  assert.strictEqual(nt.name, "BTPA-1 · New work");
  assert.strictEqual(ctx.workspaceState.get("tabs")["BTPA-1 · New work"], "s2");

  // new request tab runs claude-new in the work root
  await fake.commands.get("claudeWorksessions.newRequest")();
  assert.deepStrictEqual(fake.terminals[3].sent, ["claude-new"]);
  assert.strictEqual(fake.terminals[3].cwd, root);

  // closing a tab unlinks it
  fake.listeners.close.forEach(f => f(t));
  assert.strictEqual(allItems(p).find(([c]) => c.session?.id === "s1")[1].iconPath.id, "comment-discussion");

  // copy id, reveal
  await fake.commands.get("claudeWorksessions.copyId")({ session: { id: "s1" } });
  await fake.commands.get("claudeWorksessions.reveal")(reqEl);
  await fake.commands.get("claudeWorksessions.revealInOS")(reqEl);
  assert.deepStrictEqual(fake.executed.filter(e => e[0] !== "workbench.action.terminal.renameWithArg").map(e => e[0]),
                         ["clipboard", "revealInExplorer", "revealFileInOS"]);
});

test("tabs are relinked by name after a reload, and a failing claude-sessions shows its error", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cws-ext-"));
  const bad = path.join(dir, "claude-sessions");
  fs.writeFileSync(bad, "#!/bin/sh\necho boom >&2\nexit 1\n", { mode: 0o755 });
  const fake = fakeVscode({ sessionsCommand: bad });
  fake.terminals.push({ name: "BTPA-1 · old" });
  const ctx = context();
  await ctx.workspaceState.update("tabs", { "BTPA-1 · old": "s9" });
  load(fake).activate(ctx);
  await settle(ctx);
  const view = ctx.subscriptions[0];
  assert.strictEqual(view.message, "claude-sessions failed: boom");
  assert.strictEqual(view.provider.isOpen("s9"), true);
  assert.deepStrictEqual(view.provider.getChildren(undefined), []);
});
