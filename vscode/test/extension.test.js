// extension.js against a fake vscode API: activates, loads data from a stub claude-sessions,
// renders every tree item in every grouping, and opens / links tabs.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const Module = require("module");

// Never touch the real handoff folder or start a real VS Code from the tests.
process.env.CWS_HANDOFF_DIR = fs.mkdtempSync(path.join(os.tmpdir(), "cws-handoff-"));
process.env.CWS_CODE_CLI = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "cws-code-")), "code");
fs.writeFileSync(process.env.CWS_CODE_CLI, `#!/bin/sh\necho "$*" >> "${process.env.CWS_CODE_CLI}.log"\n`, { mode: 0o755 });

function fakeVscode(settings, { chat = false, folder } = {}) {
  const commands = new Map(), executed = [], terminals = [], listeners = {}, messages = [], answers = [], views = {};
  // Quick picks and input boxes take the next scripted answer: a function of the items, or a value.
  const answer = items => { const a = answers.shift(); return typeof a === "function" ? a(items) : a; };
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
    ProgressLocation: { Notification: 15 },
    RelativePattern: class { constructor(base, pattern) { this.base = base; this.pattern = pattern; } },
    Uri: { file: p => ({ fsPath: p }) },
    env: { clipboard: { writeText: async t => executed.push(["clipboard", t]) }, appRoot: "/nonexistent" },
    workspace: {
      workspaceFolders: folder ? [{ uri: { fsPath: folder } }] : undefined,
      getConfiguration: () => ({ get: (k, d) => (k in settings ? settings[k] : d) }),
      onDidChangeConfiguration: on("config"),
      createFileSystemWatcher: pattern => ({ onDidChange() {}, onDidDelete() {}, dispose() {},
        onDidCreate(f) { (listeners["watch:" + pattern.pattern] ||= []).push(f); } }),
    },
    window: {
      terminals, activeTerminal: undefined,
      createTreeView: (id, opts) => ({ id, provider: opts.treeDataProvider, dispose() {} }),
      createTerminal: opts => {
        const t = { ...opts, sent: [], sendText(s) { this.sent.push(s); }, show() { vscode.window.activeTerminal = this; } };
        terminals.push(t);
        return t;
      },
      showQuickPick: async items => answer(items),
      showInputBox: async opts => { const v = answer(); return opts && opts.validateInput && v && opts.validateInput(v) ? undefined : v; },
      createQuickPick: () => {
        const qp = { items: [], value: "", selectedItems: [], accept: null, hide: null,
          onDidAccept(f) { this.accept = f; }, onDidHide(f) { this.hide = f; }, dispose() {},
          show() {
            const a = answer(this.items);
            if (a === undefined) return this.hide();
            if (typeof a === "string") this.value = a; else this.selectedItems = [a];
            this.accept();
          } };
        return qp;
      },
      withProgress: (opts, fn) => fn(),
      showInformationMessage: async m => messages.push(["info", m]),
      showWarningMessage: async m => messages.push(["warn", m]),
      showErrorMessage: async m => messages.push(["error", m]),
      registerWebviewViewProvider: (id, provider) => { views[id] = provider; return { dispose() {} }; },
      onDidCloseTerminal: on("close"),
      onDidChangeActiveTerminal: on("active"),
    },
    commands: {
      registerCommand: (name, fn) => { commands.set(name, fn); return { dispose() {} }; },
      getCommands: async () => [...commands.keys(), ...(chat ? ["claude-vscode.editor.open"] : [])],
      executeCommand: async (name, arg, ...more) => {
        executed.push(name === "claude-vscode.editor.open" ? [name, arg, ...more] : [name, arg]);
        if (name === "workbench.action.terminal.renameWithArg") vscode.window.activeTerminal.name = arg.name;
      },
    },
  };
  return { vscode, commands, executed, terminals, listeners, messages, answers, views };
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
  const fake = fakeVscode({ sessionsCommand: bin, openIn: "terminal" });
  const ext = load(fake);
  const ctx = context();
  await ext.activate(ctx);
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
  fake.answers.push(items => items.find(i => i.g === "ticket"));
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
  assert.deepStrictEqual(fake.executed.filter(e => !["workbench.action.terminal.renameWithArg", "setContext"].includes(e[0])).map(e => e[0]),
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
  await load(fake).activate(ctx);
  await settle(ctx);
  const view = ctx.subscriptions[0];
  assert.strictEqual(view.message, "claude-sessions failed: boom");
  assert.strictEqual(view.provider.isOpen("s9"), true);
  assert.deepStrictEqual(view.provider.getChildren(undefined), []);
});

// A work root with one request, stub claude-sessions / claude-search, a config and skills.
async function world(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cws-cmd-"));
  const root = path.join(dir, "ws"), bin = path.join(dir, "bin");
  const A = { path: path.join(root, "2026/09/22/10-00-00_a"), name: "demo", ticket: "BTPA-1",
              task_type: "security", profile: "work" };
  fs.mkdirSync(A.path, { recursive: true });
  fs.mkdirSync(bin);
  fs.writeFileSync(path.join(A.path, ".session.json"), JSON.stringify({ name: "demo", task_type: "security" }));
  const now = Date.now() / 1000;
  const data = { work_root: root, sessions: [
    { id: "s1", mtime: now - 60, cwd: A.path, in_work_root: true, title: "Fix the firewall",
      first_prompt: "first", last_prompt: "open port 443", request: A },
    { id: "s0", mtime: now - 7200, cwd: root, in_work_root: true, title: "Root chat",
      first_prompt: "hi", last_prompt: null, request: null },
  ] };
  fs.writeFileSync(path.join(dir, "data.json"), JSON.stringify(data));
  fs.writeFileSync(path.join(bin, "claude-sessions"), `#!/bin/sh\ncat "${dir}/data.json"\n`, { mode: 0o755 });
  fs.writeFileSync(path.join(dir, "search.csv"),
    'rank,level,score,session_id,start,end,worked,task,ticket,title,folder,why,snippet,resume\n' +
    `1,strong,9,s1,2026-09-22T10:00,,,,BTPA-1,Fix the firewall,${A.path},"title: firewall","you: ""open port"""` +
    `,cd x && claude-resume -p work --resume s1\n` +
    `2,likely,3,zz-outside,2026-09-01T10:00,,,,,Elsewhere,/repo,why,snip,cd /repo && claude-resume --resume zz-outside\n`);
  fs.writeFileSync(path.join(bin, "claude-search"),
    `#!/bin/sh\necho "$*" >> "${dir}/search.log"\ncase "$*" in *nothing*) exit 0;; *broken*) echo bad >&2; exit 1;; esac\ncat "${dir}/search.csv"\n`,
    { mode: 0o755 });
  // config and skills under a throwaway HOME
  const home = path.join(dir, "home");
  fs.mkdirSync(path.join(home, ".claude-personal/skills/weekly-review"), { recursive: true });
  fs.writeFileSync(path.join(home, ".claude-personal/skills/weekly-review/SKILL.md"),
                   "---\nname: weekly-review\ndescription: Fill in the tracker\n---\n");
  fs.writeFileSync(path.join(dir, "config.env"),
                   'CWS_PROFILES="personal work"\nCWS_TASK_TYPES="permissions, tooling"\n');
  const saved = { HOME: process.env.HOME, CWS_CONFIG: process.env.CWS_CONFIG };
  process.env.HOME = home; process.env.CWS_CONFIG = path.join(dir, "config.env");
  t.after(() => { for (const [k, v] of Object.entries(saved)) (v === undefined ? delete process.env[k] : process.env[k] = v); });

  const fake = fakeVscode({ sessionsCommand: path.join(bin, "claude-sessions"), openIn: "terminal" });
  const ctx = context();
  await load(fake).activate(ctx);
  await settle(ctx);
  const run = (name, ...a) => fake.commands.get("claudeWorksessions." + name)(...a);
  return { dir, root, A, data, fake, ctx, run, bar: ctx.subscriptions[0].provider, view: ctx.subscriptions[0] };
}

function fakeWebview() {
  const posted = [];
  let handler;
  return { posted, send: m => handler(m),
           view: { webview: { options: {}, html: "", postMessage: m => posted.push(m),
                              onDidReceiveMessage: f => { handler = f; } } } };
}

test("the search box filters the tree, counts matches and searches contents on Enter", async t => {
  const w = await world(t);
  const box = w.fake.views["claudeWorksessions.search"];
  const web = fakeWebview();
  box.resolveWebviewView(web.view);
  assert.match(web.view.webview.html, /type="search"/);
  assert.match(web.view.webview.html, /Content-Security-Policy/);

  web.send({ type: "filter", value: "443" });
  assert.strictEqual(w.bar.filter, "443");
  const items = allItems(w.bar);
  assert.deepStrictEqual(items.map(([, it]) => it.label), ["2026-09-22", "demo", "Fix the firewall"]);
  assert.ok(items.every(([c, it]) => c.kind === "session" || it.collapsibleState === 2));   // all expanded
  assert.ok(items[0][1].id.includes("|443|"));
  assert.deepStrictEqual(web.posted.at(-1), { type: "hint", text: "1 of 2 sessions · Enter to search contents" });
  assert.ok(w.fake.executed.some(e => e[0] === "setContext" && e[1] === "claudeWorksessions.filtering"));

  web.send({ type: "filter", value: "zzz" });
  assert.match(w.view.message, /No session matches "zzz"/);

  // Enter: claude-search, then pick the first hit → opens its tab
  w.fake.answers.push(items => items[0]);
  web.send({ type: "search", value: "firewall" });
  await new Promise(r => setTimeout(r, 300));
  assert.match(fs.readFileSync(path.join(w.dir, "search.log"), "utf8"), /^firewall --csv - --no-pick --limit 25$/m);
  assert.deepStrictEqual(w.fake.terminals.at(-1).sent, ["claude-resume -p 'work' --resume 's1'"]);

  // clear: the box is told, the tree shows everything again
  await w.run("clearFilter");
  assert.deepStrictEqual(web.posted.filter(m => m.type === "set").at(-1), { type: "set", value: "" });
  assert.strictEqual(w.bar.filter, "");
  assert.strictEqual(w.view.message, undefined);
  await w.run("focusSearch");
  assert.deepStrictEqual(web.posted.at(-1), { type: "focus" });
});

test("search commands: AI flag, hits outside the list, no hits, failure", async t => {
  const w = await world(t);
  w.fake.answers.push("fire wall", items => items[1]);
  await w.run("searchAi");
  assert.match(fs.readFileSync(path.join(w.dir, "search.log"), "utf8"), /^fire wall --csv - --no-pick --limit 25 --ai$/m);
  const t1 = w.fake.terminals.at(-1);
  assert.strictEqual(t1.name, "Elsewhere");
  assert.deepStrictEqual(t1.sent, ["cd /repo && claude-resume --resume zz-outside"]);
  w.fake.answers.push("nothing");
  await w.run("search");
  assert.deepStrictEqual(w.fake.messages.at(-1), ["info", 'No sessions match "nothing".']);
  w.fake.answers.push("broken");
  await w.run("search");
  assert.deepStrictEqual(w.fake.messages.at(-1), ["error", "claude-search failed: bad"]);
  w.fake.answers.push(undefined);
  await w.run("search");                                   // cancelled: nothing happens
  w.fake.answers.push("firewall", undefined);
  await w.run("search");                                   // no pick: nothing opens
  assert.strictEqual(w.fake.terminals.length, 1);
});

test("audit runs claude-audit for the chosen period and view", async t => {
  const w = await world(t);
  w.fake.answers.push(items => items.find(i => i.period === "week"), items => items[0]);
  await w.run("audit");
  assert.deepStrictEqual(w.fake.terminals.at(-1).sent, ["claude-audit --week"]);
  assert.strictEqual(w.fake.terminals.at(-1).name, "audit · This week");
  assert.strictEqual(w.fake.terminals.at(-1).cwd, w.root);
  w.fake.answers.push(items => items.find(i => i.period === "day"), "2026-09-01", items => items[1]);
  await w.run("audit");
  assert.deepStrictEqual(w.fake.terminals.at(-1).sent, ["claude-audit --day '2026-09-01' --detail"]);
  w.fake.answers.push(items => items.find(i => i.period === "lastweek"), items => items[0]);
  await w.run("audit");
  assert.match(w.fake.terminals.at(-1).sent[0], /^claude-audit --week '\d{4}-\d{2}-\d{2}'$/);
  const n = w.fake.terminals.length;
  w.fake.answers.push(undefined);
  await w.run("audit");
  w.fake.answers.push(items => items.find(i => i.period === "day"), "not a date");
  await w.run("audit");
  w.fake.answers.push(items => items[0], undefined);
  await w.run("audit");
  assert.strictEqual(w.fake.terminals.length, n);
});

test("set task type on a session, a request, the focused tab, or a picked session", async t => {
  const w = await world(t);
  const meta = () => JSON.parse(fs.readFileSync(path.join(w.A.path, ".session.json"), "utf8"));
  const sEl = allItems(w.bar).find(([c]) => c.session?.id === "s1")[0];
  const rEl = allItems(w.bar).find(([c]) => c.kind === "request" && !c.request.root)[0];

  w.fake.answers.push(items => {
    assert.deepStrictEqual(items.map(i => i.label), ["security", "permissions", "tooling"]);
    assert.strictEqual(items[0].description, "current");
    return items[1];
  });
  await w.run("setType", sEl);
  assert.deepStrictEqual(meta().session_types, { s1: "permissions" });
  assert.match(w.fake.messages.at(-1)[1], /\(session s1\): security → permissions/);

  w.fake.answers.push("incident");                          // typed, not in the list
  await w.run("setType", rEl);
  assert.strictEqual(meta().task_type, "incident");

  await w.run("open", sEl);                                 // focused tab → its session, no picker
  w.fake.answers.push(items => items[0]);
  await w.run("setType");
  assert.strictEqual(Object.keys(meta().session_types).length, 1);

  w.fake.vscode.window.activeTerminal = undefined;          // nothing focused → pick a session
  w.fake.answers.push(items => items.find(i => i.session.id === "s0"));
  await w.run("setType");
  assert.match(w.fake.messages.at(-1)[1], /no request folder/);

  w.fake.answers.push(items => items.find(i => i.session.id === "s1"), undefined);
  await w.run("setType");                                   // cancelled
  fs.unlinkSync(path.join(w.A.path, ".session.json"));
  await w.run("setType", rEl);
  assert.match(w.fake.messages.at(-1)[1], /No .session.json in 10-00-00_a/);
  w.fake.answers.push(undefined);
  await w.run("setType");                                   // no session picked
});

test("recent sessions, go to request, skills, resume by id, new window", async t => {
  const w = await world(t);
  w.fake.answers.push(items => {
    assert.deepStrictEqual(items.map(i => i.label), ["Fix the firewall", "Root chat"]);
    assert.match(items[0].description, /^BTPA-1 · demo · 1m$/);
    assert.strictEqual(items[0].detail, "last: open port 443");
    assert.strictEqual(items[1].description.split(" · ")[0], "work root");
    return items[0];
  });
  await w.run("recentSessions");
  assert.deepStrictEqual(w.fake.terminals.at(-1).sent, ["claude-resume -p 'work' --resume 's1'"]);
  w.fake.answers.push(undefined);
  await w.run("recentSessions");

  for (const [how, check] of [
    ["window", () => assert.deepStrictEqual(w.fake.executed.at(-1), ["vscode.openFolder", { fsPath: w.A.path }])],
    ["explorer", () => assert.deepStrictEqual(w.fake.executed.at(-1), ["revealInExplorer", { fsPath: w.A.path }])],
    ["session", () => assert.deepStrictEqual(w.fake.terminals.at(-1).sent, ['CLAUDE_CONFIG_DIR="$HOME/.claude-work" claude'])],
  ]) {
    w.fake.answers.push(items => { assert.deepStrictEqual(items.map(i => i.label), ["demo"]); return items[0]; },
                        items => items.find(i => i.how === how));
    await w.run("goToRequest");
    check();
  }
  w.fake.answers.push(undefined);
  await w.run("goToRequest");
  w.fake.answers.push(items => items[0], undefined);
  await w.run("goToRequest");

  w.fake.answers.push(items => { assert.deepStrictEqual(items.map(i => i.label), ["/weekly-review"]); return items[0]; });
  await w.run("runSkill");
  const sk = w.fake.terminals.at(-1);
  assert.deepStrictEqual(sk.sent, ["claude-new --prompt '/weekly-review' 'weekly review'"]);
  assert.strictEqual(sk.name, "new request · /weekly-review");
  assert.strictEqual(w.bar.pending.at(-1).kind, "new");
  w.fake.answers.push(undefined);
  await w.run("runSkill");

  w.fake.answers.push("s0");
  await w.run("resumeById");
  assert.deepStrictEqual(w.fake.terminals.at(-1).sent, ["claude-resume --resume 's0'"]);
  w.fake.answers.push("abcdef12-0000");
  await w.run("resumeById");
  assert.deepStrictEqual(w.fake.terminals.at(-1).sent, ["claude-resume --resume 'abcdef12-0000'"]);
  const n = w.fake.terminals.length;
  w.fake.answers.push("not an id!");
  await w.run("resumeById");
  assert.strictEqual(w.fake.terminals.length, n);

  await w.run("openInWindow", { request: w.A });
  assert.deepStrictEqual(w.fake.executed.at(-1), ["vscode.openFolder", { fsPath: w.A.path }]);
});

test("run skill with no skills installed says so", async t => {
  const w = await world(t);
  fs.rmSync(path.join(process.env.HOME, ".claude-personal/skills"), { recursive: true });
  await w.run("runSkill");
  assert.match(w.fake.messages.at(-1)[1], /No skills found/);
});

// --- chat mode: the official Claude Code extension --------------------------------------
const HAND = () => process.env.CWS_HANDOFF_DIR;
const notes = () => fs.readdirSync(HAND()).map(n => JSON.parse(fs.readFileSync(path.join(HAND(), n), "utf8")));
const codeLog = () => { try { return fs.readFileSync(process.env.CWS_CODE_CLI + ".log", "utf8"); } catch { return ""; } };
const chatCalls = fake => fake.executed.filter(e => e[0] === "claude-vscode.editor.open");
const clearHand = () => { for (const n of fs.readdirSync(HAND())) fs.unlinkSync(path.join(HAND(), n)); };

async function chatWorld(t, { folder, openIn } = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cws-chat-"));
  const root = path.join(dir, "ws");
  const A = { path: path.join(root, "2026/09/22/10-00-00_a"), name: "demo", ticket: "BTPA-1", task_type: "", profile: "work" };
  const B = { path: path.join(root, "2026/09/22/11-00-00_b"), name: "other", ticket: "", task_type: "", profile: "" };
  for (const r of [A, B]) fs.mkdirSync(r.path, { recursive: true });
  const now = Date.now() / 1000;
  const data = { work_root: root, sessions: [
    { id: "sa", mtime: now - 60, cwd: A.path, in_work_root: true, title: "In A", first_prompt: "x", last_prompt: "y", request: A },
    { id: "sb", mtime: now - 90, cwd: B.path, in_work_root: true, title: "In B", first_prompt: "x", last_prompt: "y", request: B },
  ] };
  const { bin } = stubSessions(dir, data);
  fs.writeFileSync(path.join(path.dirname(bin), "claude-search"),
    '#!/bin/sh\nprintf "rank,session_id,title,folder,resume\\n1,zz,Elsewhere,/repo,x\\n"\n', { mode: 0o755 });
  const fake = fakeVscode({ sessionsCommand: bin, ...(openIn ? { openIn } : {}) },
                          { chat: true, folder: folder === undefined ? A.path : folder });
  const ctx = context();
  await load(fake).activate(ctx);
  await settle(ctx);
  const run = (name, ...a) => fake.commands.get("claudeWorksessions." + name)(...a);
  const el = id => allItems(ctx.subscriptions[0].provider).find(([c]) => c.session?.id === id)[0];
  const reqEl = r => ({ kind: "request", request: r });
  return { A, B, root, fake, ctx, run, el, reqEl };
}

test("chat: sessions in this window's folder open in the official chat, others hand off to their window", async t => {
  clearHand();
  const w = await chatWorld(t);
  await w.run("open", w.el("sa"));
  assert.deepStrictEqual(chatCalls(w.fake), [["claude-vscode.editor.open", "sa", undefined]]);
  assert.strictEqual(w.fake.terminals.length, 0);

  const before = codeLog();
  await w.run("open", w.el("sb"));
  assert.deepStrictEqual(notes().map(n => [n.folder, n.session, n.prompt]), [[w.B.path, "sb", null]]);
  await new Promise(r => setTimeout(r, 200));
  assert.strictEqual(codeLog().slice(before.length).trim(), w.B.path);        // `code <folder>`
  assert.strictEqual(chatCalls(w.fake).length, 1);                           // not opened here

  clearHand();
  await w.run("addSession", w.reqEl(w.A));                                   // this window: a new chat
  assert.deepStrictEqual(chatCalls(w.fake).at(-1), ["claude-vscode.editor.open", undefined, undefined]);
  await w.run("addSession", w.reqEl(w.B));                                   // elsewhere: a note
  assert.deepStrictEqual(notes().map(n => [n.folder, n.session]), [[w.B.path, null]]);

  // new request and skills: claude-new -c in a terminal, which closes itself when done
  await w.run("newRequest");
  assert.deepStrictEqual(w.fake.terminals.at(-1).sent, ["claude-new -c && exit"]);
  clearHand();
  w.fake.answers.push("zz-query", items => items[0]);
  await w.run("search");                                                     // a hit outside the list
  assert.deepStrictEqual(notes().map(n => [n.folder, n.session]), [["/repo", "zz"]]);
});

test("chat: the window takes notes addressed to its folder, once, and clears stale ones", async t => {
  clearHand();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cws-notes-"));
  const mine = path.join(dir, "mine"), other = path.join(dir, "other");
  fs.mkdirSync(mine); fs.mkdirSync(other);
  const now = Date.now() / 1000;
  const put = (name, note) => fs.writeFileSync(path.join(HAND(), name + ".json"),
                                               typeof note === "string" ? note : JSON.stringify(note));
  put("fresh", { folder: mine, session: "s1", prompt: null, at: now - 5 });
  put("prompt", { folder: mine, session: null, prompt: "/weekly-review", at: now - 5 });
  put("elsewhere", { folder: other, session: "s2", prompt: null, at: now - 5 });
  put("late", { folder: mine, session: "s3", prompt: null, at: now - 700 });
  put("ancient", { folder: other, session: "s4", prompt: null, at: now - 90000 });
  put("broken", "{nope");
  const w = await chatWorld(t, { folder: mine });
  const got = chatCalls(w.fake).map(c => c.slice(1));
  assert.strictEqual(got.length, 2);
  assert.ok(got.some(c => c[0] === undefined && c[1] === "/weekly-review"));
  assert.ok(got.some(c => c[0] === "s1" && c[1] === undefined));
  assert.deepStrictEqual(fs.readdirSync(HAND()).sort(), ["broken.json", "elsewhere.json", "late.json"]);

  // a note arriving later is picked up through the watcher
  put("later", { folder: mine, session: "s5", prompt: null, at: Date.now() / 1000 });
  for (const f of w.fake.listeners["watch:*.json"]) await f();
  assert.deepStrictEqual(chatCalls(w.fake).at(-1), ["claude-vscode.editor.open", "s5", undefined]);
  assert.ok(!fs.existsSync(path.join(HAND(), "later.json")));
});

test("chat: openIn terminal, or the Claude Code extension missing, keeps terminal tabs", async t => {
  clearHand();
  const w = await chatWorld(t, { openIn: "terminal" });
  await w.run("open", w.el("sb"));
  assert.deepStrictEqual(w.fake.terminals.at(-1).sent, ["claude-resume --resume 'sb'"]);
  assert.strictEqual(chatCalls(w.fake).length, 0);

  // chat asked for but not available: terminal tabs, and the panel says why
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cws-nochat-"));
  const { bin } = stubSessions(dir, { work_root: dir, sessions: [] });
  const fake = fakeVscode({ sessionsCommand: bin }, { chat: false, folder: dir });
  const ctx = context();
  await load(fake).activate(ctx);
  await settle(ctx);
  assert.match(ctx.subscriptions[0].message || "", /isn't installed|terminal tabs/);
});
