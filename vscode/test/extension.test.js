// extension.js against a fake vscode API: activates, loads data from a stub claude-sessions,
// renders every tree item in every grouping, and opens / links tabs.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const Module = require("module");

// The deleted-sessions bin the tests see: never the real one
process.env.CWS_TRASH_DIR = fs.mkdtempSync(path.join(os.tmpdir(), "cws-bin-"));

function fakeVscode(settings) {
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
    ThemeIcon: Object.assign(class { constructor(id, color) { this.id = id; this.color = color; } },
                             { Folder: { id: "folder-theme" }, File: { id: "file-theme" } }),
    ThemeColor: class { constructor(id) { this.id = id; } },
    TerminalLocation: { Panel: 1, Editor: 2 },
    ProgressLocation: { Notification: 15 },
    RelativePattern: class { constructor(base, pattern) { this.base = base; this.pattern = pattern; } },
    Uri: { file: p => ({ fsPath: p }) },
    env: { clipboard: { writeText: async t => executed.push(["clipboard", t]) } },
    workspace: {
      textDocuments: [],
      getConfiguration: () => ({ get: (k, d) => (k in settings ? settings[k] : d) }),
      onDidChangeConfiguration: on("config"),
      createFileSystemWatcher: pattern => {
        const keep = f => (listeners["watch:" + pattern.pattern] ||= []).push(f);
        return { onDidChange: keep, onDidCreate: keep, onDidDelete: keep, dispose() {} };
      },
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
      showWarningMessage: async (m, opts, ...items) => {
        if (!(opts && opts.modal)) return messages.push(["warn", m]);
        messages.push(["modal", m, opts.detail]);
        return answer(items);
      },
      showErrorMessage: async m => messages.push(["error", m]),
      registerWebviewViewProvider: (id, provider) => { views[id] = provider; return { dispose() {} }; },
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
  const fake = fakeVscode({ sessionsCommand: bin });
  const ext = load(fake);
  const ctx = context();
  ext.activate(ctx);
  await settle(ctx);
  const view = ctx.subscriptions[0];
  const p = view.provider;
  assert.strictEqual(view.description, "By day · Last activity");
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
  assert.strictEqual(view.description, "By ticket · Last activity");

  // sort: remembered, shown in the description, applied to the tree
  fake.answers.push(items => {
    assert.deepStrictEqual(items.map(i => i.k), ["activity", "started", "name"]);
    assert.strictEqual(items[0].description, "current");
    return items.find(i => i.k === "name");
  });
  await fake.commands.get("claudeWorksessions.sort")();
  assert.strictEqual(ctx.globalState.get("sort"), "name");
  assert.strictEqual(view.description, "By ticket · Name (A–Z)");
  assert.strictEqual(p.opts().sort, "name");
  fake.answers.push(undefined);
  await fake.commands.get("claudeWorksessions.sort")();                      // cancelled: unchanged
  assert.strictEqual(p.sort, "name");
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
  load(fake).activate(ctx);
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

  const fake = fakeVscode({ sessionsCommand: path.join(bin, "claude-sessions") });
  const ctx = context();
  load(fake).activate(ctx);
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
  // the search runs claude-search in the background: wait for its tab, not a fixed time
  for (let i = 0; i < 100 && !w.fake.terminals.length; i++) await new Promise(r => setTimeout(r, 50));
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

test("files: a Files node per request, folders, opening, reveal, copy, and what a session wrote", async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cws-files-"));
  const root = path.join(dir, "ws");
  const A = { path: path.join(root, "2026/09/22/10-00-00_a"), name: "demo", ticket: "BTPA-1", task_type: "",
              profile: "", files: ["notes.md", "out/report.csv", "out/brainlabs.csv"], files_truncated: true };
  const B = { path: path.join(root, "2026/09/22/11-00-00_b"), name: "empty", ticket: "", task_type: "",
              profile: "", files: [], files_truncated: false };
  for (const r of [A, B]) fs.mkdirSync(r.path, { recursive: true });
  const now = Date.now() / 1000;
  const written = [path.join(A.path, "notes.md"), ...Array.from({ length: 9 }, (_, i) => path.join(A.path, `f${i}.txt`)),
                   path.join(os.homedir(), "elsewhere.py")];
  const data = { work_root: root, sessions: [
    { id: "sa", mtime: now - 60, cwd: A.path, in_work_root: true, title: "With files", first_prompt: "x",
      last_prompt: "y", written, request: A },
    { id: "sb", mtime: now - 90, cwd: B.path, in_work_root: true, title: "No files", first_prompt: "x",
      last_prompt: "y", written: [], request: B },
  ] };
  const { bin } = stubSessions(dir, data);
  const fake = fakeVscode({ sessionsCommand: bin, openIn: "terminal" });
  const ctx = context();
  await load(fake).activate(ctx);
  await settle(ctx);
  const p = ctx.subscriptions[0].provider;
  const run = (name, ...a) => fake.commands.get("claudeWorksessions." + name)(...a);

  let items = allItems(p);
  const filesEl = items.find(([c]) => c.kind === "files");
  assert.strictEqual(items.filter(([c]) => c.kind === "files").length, 1);        // not for the empty request
  assert.deepStrictEqual([filesEl[1].label, filesEl[1].description, filesEl[1].iconPath.id], ["Files", "3+", "files"]);
  assert.strictEqual(filesEl[1].collapsibleState, 1);
  const tree = items.filter(([c]) => c.kind === "dir" || c.kind === "file");
  assert.deepStrictEqual(tree.map(([c]) => c.kind === "dir" ? c.name + "/" : c.rel),
                         ["out/", "out/brainlabs.csv", "out/report.csv", "notes.md"]);
  const [dirEl, dirIt] = tree[0];
  assert.deepStrictEqual([dirIt.label, dirIt.iconPath.id, dirIt.resourceUri.fsPath, dirIt.contextValue],
                         ["out", "folder-theme", path.join(A.path, "out/"), "dir"]);
  const md = tree.find(([c]) => c.rel === "notes.md");
  assert.deepStrictEqual([md[1].label.fsPath, md[1].contextValue, md[1].tooltip], [path.join(A.path, "notes.md"), "file-md", "notes.md"]);

  // hover: what the session wrote, relative to its request, capped at 8
  const hover = items.find(([c]) => c.session?.id === "sa")[1].tooltip.value;
  assert.match(hover, /\*\*Wrote:\*\* notes\.md, f0\.txt, .*f6\.txt and 3 more/);
  const noWrite = items.find(([c]) => c.session?.id === "sb")[1].tooltip.value;
  assert.doesNotMatch(noWrite, /Wrote/);

  // open: Markdown in the preview, everything else in the editor
  await run("openFile", md[0]);
  assert.deepStrictEqual(fake.executed.at(-1), ["markdown.showPreview", { fsPath: path.join(A.path, "notes.md") }]);
  await run("openFile", tree[1][0]);
  assert.deepStrictEqual(fake.executed.at(-1), ["vscode.open", { fsPath: path.join(A.path, "out/brainlabs.csv") }]);
  await run("revealFile", dirEl);
  assert.deepStrictEqual(fake.executed.at(-1), ["revealFileInOS", { fsPath: path.join(A.path, "out/") }]);
  await run("copyPath", md[0]);
  assert.deepStrictEqual(fake.executed.at(-1), ["clipboard", path.join(A.path, "notes.md")]);

  // search: a file name finds its request and narrows the files shown, all expanded
  p.setFilter("brainlabs");
  items = allItems(p);
  assert.deepStrictEqual(items.filter(([c]) => c.kind === "file").map(([c]) => c.rel), ["out/brainlabs.csv"]);
  assert.ok(items.filter(([c]) => c.kind === "files" || c.kind === "dir").every(([, it]) => it.collapsibleState === 2));
  assert.ok(!items.some(([c]) => c.session?.id === "sb"));
});

test("copy for email: from the sidebar, a menu URI, the editor or a preview; saves first; reports errors", async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cws-mail-"));
  const bin = path.join(dir, "bin");
  fs.mkdirSync(bin);
  const log = path.join(dir, "mail.log");
  fs.writeFileSync(path.join(bin, "claude-sessions"), `#!/bin/sh\necho '{"work_root":"${dir}","sessions":[]}'\n`, { mode: 0o755 });
  fs.writeFileSync(path.join(bin, "claude-md-email"),
    `#!/bin/sh\necho "$1" >> "${log}"\ncase "$1" in *broken*) echo "claude-md-email: pandoc is not installed" >&2; exit 1;; esac\n`, { mode: 0o755 });
  const fake = fakeVscode({ sessionsCommand: path.join(bin, "claude-sessions"), openIn: "terminal" });
  const ctx = context();
  await load(fake).activate(ctx);
  await settle(ctx);
  const run = arg => fake.commands.get("claudeWorksessions.copyForEmail")(arg);
  const calls = () => fs.readFileSync(log, "utf8").trim().split("\n");
  const doc = (p, extra = {}) => ({ languageId: "markdown", uri: { fsPath: p }, isDirty: false, save: async function () { this.saved = true; }, ...extra });

  await run({ request: { path: "/w/req" }, rel: "out/notes.md" });              // sidebar file
  await run({ fsPath: "/w/menu.md" });                                          // explorer / editor title
  const dirty = doc("/w/open.md", { isDirty: true });
  fake.vscode.workspace.textDocuments.push(dirty);
  fake.vscode.window.activeTextEditor = { document: dirty };
  await run();                                                                  // the active editor
  assert.ok(dirty.saved);
  fake.vscode.window.activeTextEditor = undefined;
  fake.vscode.workspace.textDocuments.push(doc("/w/other/preview-me.md"));
  fake.vscode.window.tabGroups = { activeTabGroup: { activeTab: { label: "Preview preview-me.md" } } };
  await run();                                                                  // a Markdown preview
  assert.deepStrictEqual(calls(), ["/w/req/out/notes.md", "/w/menu.md", "/w/open.md", "/w/other/preview-me.md"]);
  assert.deepStrictEqual(fake.messages.at(-1), ["info", "Copied preview-me.md for email — paste it into Outlook."]);

  fake.vscode.window.tabGroups = { activeTabGroup: { activeTab: { label: "Preview unknown.md" } } };
  await run();
  assert.match(fake.messages.at(-1)[1], /Open or select a Markdown file/);
  fake.vscode.window.tabGroups = undefined;
  await run();
  assert.match(fake.messages.at(-1)[1], /Open or select a Markdown file/);

  await run({ fsPath: "/w/broken.md" });
  assert.deepStrictEqual(fake.messages.at(-1), ["error", "claude-md-email: pandoc is not installed"]);
});

test("pins: Pin puts a session or request in a Pinned group on top; Unpin takes it out", async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cws-pinx-"));
  const root = path.join(dir, "ws");
  const A = { path: path.join(root, "2026/09/22/10-00-00_a"), name: "demo", ticket: "BTPA-1", task_type: "",
              profile: "", files: ["notes.md"], files_truncated: false };
  const B = { path: path.join(root, "2026/09/21/10-00-00_b"), name: "older", ticket: "", task_type: "",
              profile: "", files: [], files_truncated: false };
  for (const r of [A, B]) fs.mkdirSync(r.path, { recursive: true });
  const now = Date.now() / 1000;
  const data = { work_root: root, sessions: [
    { id: "sa", mtime: now - 60, cwd: A.path, in_work_root: true, title: "Newer", request: A },
    { id: "sb", mtime: now - 90, cwd: B.path, in_work_root: true, title: "Older", request: B },
  ] };
  const { bin } = stubSessions(dir, data);
  const fake = fakeVscode({ sessionsCommand: bin, openIn: "terminal" });
  const ctx = context();
  await load(fake).activate(ctx);
  await settle(ctx);
  const p = ctx.subscriptions[0].provider;
  const run = (name, el) => fake.commands.get("claudeWorksessions." + name)(el);
  const top = () => p.getChildren(undefined);
  const find = (items, pred) => items.find(([c]) => pred(c));

  assert.notStrictEqual(top()[0].kind, "pinned");
  let items = allItems(p);
  const sb = find(items, c => c.session?.id === "sb");
  assert.strictEqual(sb[1].contextValue, "session");
  await run("pin", sb[0]);
  const reqA = find(allItems(p), c => c.kind === "request" && c.request.name === "demo");
  assert.strictEqual(reqA[1].contextValue, "request");
  await run("pin", reqA[0]);
  const saved = JSON.parse(fs.readFileSync(path.join(root, "_config", "pinned.json"), "utf8"));
  assert.deepStrictEqual([Object.keys(saved.sessions), Object.keys(saved.requests)], [["sb"], ["2026/09/22/10-00-00_a"]]);

  items = allItems(p);
  const [pinGroup, pinItem] = items[0];
  assert.deepStrictEqual([pinGroup.kind, pinItem.label, pinItem.description, pinItem.iconPath.id, pinItem.collapsibleState],
                         ["pinned", "Pinned", "2", "pinned", 2]);
  const underPin = items.filter(([c]) => c.inPinned);
  assert.deepStrictEqual(underPin.map(([c]) => c.kind + ":" + (c.session?.id || c.rel || c.request?.name)),
                         ["request:demo", "session:sa", "files:demo", "file:notes.md", "session:sb"]);
  const ids = items.map(([, it]) => it.id).filter(Boolean);
  assert.strictEqual(new Set(ids).size, ids.length);                                   // copies get their own ids
  const pinnedSb = find(items, c => c.session?.id === "sb" && !c.inPinned)[1];
  assert.deepStrictEqual([pinnedSb.contextValue, pinnedSb.iconPath.id], ["session-pinned", "pinned"]);
  const inPinSb = find(items, c => c.session?.id === "sb" && c.inPinned)[1];
  assert.match(inPinSb.description, /^older · /);                                      // shows its request
  const normalA = find(items, c => c.kind === "request" && c.request.name === "demo" && !c.inPinned)[1];
  assert.deepStrictEqual([normalA.contextValue, normalA.description.split(" · ")[0]], ["request-pinned", "pinned"]);
  const firstDay = items.find(([c]) => c.kind === "group");
  assert.strictEqual(firstDay[1].collapsibleState, 2);                                 // first real group still open

  await run("unpin", find(items, c => c.session?.id === "sb")[0]);
  await run("unpin", find(allItems(p), c => c.kind === "request" && c.request.name === "demo")[0]);
  assert.notStrictEqual(top()[0].kind, "pinned");

  // a change from elsewhere (another machine, via the synced work root) is picked up
  fs.writeFileSync(path.join(root, "_config", "pinned.json"), JSON.stringify({ sessions: { sa: 1 }, requests: {} }));
  for (const f of fake.listeners["watch:_config/pinned.json"] || []) f();
  assert.strictEqual(top()[0].kind, "pinned");
});

test("delete: only sessions with no value offer it; confirm shows the impact; bin, tab closed, refresh", async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cws-del-"));
  const root = path.join(dir, "ws");
  const A = { path: path.join(root, "2026/09/23/10-00-00_a"), name: "demo", ticket: "", task_type: "", profile: "",
              files: [], files_truncated: false };
  fs.mkdirSync(A.path, { recursive: true });
  const now = Date.now() / 1000;
  const ses = (id, ok, extra = {}) => ({ id, mtime: now - 600, cwd: A.path, in_work_root: true, title: id, request: A,
    deletable: { ok, why: ok ? ["no artifacts"] : [], blocked: ok ? [] : ["x"] }, ...extra });
  const data = { work_root: root, sessions: [ses("junk", true), ses("keep", false), ses("pinme", true)] };
  const { bin, json } = stubSessions(dir, data);
  const log = path.join(dir, "del.log");
  fs.writeFileSync(path.join(path.dirname(bin), "claude-delete"), `#!/bin/sh
echo "$*" >> "${log}"
case "$1 $2" in
  "junk --json") echo '{"title":"junk","request":"demo","last_activity":"2026-09-23 10:00","deletable":true,"why":["no artifacts"],"blocked":[],"impact":["The conversation goes.","It left no files."]}';;
  "keep --json") echo '{"title":"keep","deletable":false,"why":[],"blocked":["booked in the weekly review"],"impact":[]}'; exit 1;;
  "broken --json") echo "boom" >&2; exit 2;;
  "junk --yes") echo "Moved";;
  "gone --json") echo '{"title":"gone","request":null,"last_activity":"?","deletable":true,"why":["kept out of the review (-n)"],"blocked":[],"impact":["x"]}';;
  "gone --yes") echo "no permission" >&2; exit 1;;
esac
`, { mode: 0o755 });
  const fake = fakeVscode({ sessionsCommand: bin, openIn: "terminal" });
  const ctx = context();
  await load(fake).activate(ctx);
  await settle(ctx);
  const p = ctx.subscriptions[0].provider;
  const run = el => fake.commands.get("claudeWorksessions.deleteSession")(el);
  const item = id => allItems(p).find(([c]) => c.session?.id === id);

  assert.strictEqual(item("junk")[1].contextValue, "session-del");
  assert.strictEqual(item("keep")[1].contextValue, "session");
  await fake.commands.get("claudeWorksessions.pin")(item("pinme")[0]);
  assert.strictEqual(item("pinme")[1].contextValue, "session-pinned-del");

  // open it first, so the delete closes its tab
  await fake.commands.get("claudeWorksessions.open")(item("junk")[0]);
  const tab = fake.terminals.at(-1);
  let disposed = false;
  tab.dispose = () => { disposed = true; };

  fake.answers.push(items => { assert.deepStrictEqual(items, ["Move to the bin"]); return undefined; });   // cancel
  await run(item("junk")[0]);
  assert.deepStrictEqual(fake.messages.at(-1), ["modal", 'Delete "junk"?',
    "demo · last active 2026-09-23 10:00\nIt may go: no artifacts.\n\n• The conversation goes.\n• It left no files."]);
  assert.ok(!fs.readFileSync(log, "utf8").includes("--yes"));

  fake.answers.push("Move to the bin");
  data.sessions = data.sessions.filter(s => s.id !== "junk");
  fs.writeFileSync(json, JSON.stringify(data));
  await run(item("junk")[0]);
  assert.match(fs.readFileSync(log, "utf8"), /junk --yes/);
  assert.ok(disposed);
  assert.deepStrictEqual(fake.messages.at(-1), ["info", '"junk" moved to the bin — restore it from Deleted, at the bottom of this list.']);
  assert.strictEqual(item("junk"), undefined);                                     // refreshed

  await run({ session: { id: "keep" } });                                          // refused by claude-delete
  assert.deepStrictEqual(fake.messages.at(-1), ["warn", '"keep" can\'t be deleted: booked in the weekly review.']);
  await run({ session: { id: "broken" } });
  assert.deepStrictEqual(fake.messages.at(-1), ["error", "claude-delete failed: boom"]);
  fake.answers.push("Move to the bin");
  await run({ session: { id: "gone" } });
  assert.match(fake.messages.at(-2)[2], /^Work root · last active \?/);
  assert.deepStrictEqual(fake.messages.at(-1), ["error", "claude-delete failed: no permission"]);
});

test("deleted sessions: a Deleted group at the bottom; restore, delete for good, empty", async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cws-binx-"));
  const bin = process.env.CWS_TRASH_DIR;
  for (const n of fs.readdirSync(bin)) fs.rmSync(path.join(bin, n), { recursive: true });
  const root = path.join(dir, "ws");
  const A = { path: path.join(root, "2026/09/23/10-00-00_a"), name: "demo", ticket: "", task_type: "", profile: "",
              files: [], files_truncated: false };
  fs.mkdirSync(A.path, { recursive: true });
  const now = Date.now() / 1000;
  const data = { work_root: root, sessions: [{ id: "live", mtime: now - 60, cwd: A.path, in_work_root: true, title: "Live", request: A }] };
  const { bin: sessionsBin } = stubSessions(dir, data);
  const log = path.join(dir, "del.log");
  fs.writeFileSync(path.join(path.dirname(sessionsBin), "claude-delete"),
    `#!/bin/sh\necho "$*" >> "${log}"\ncase "$*" in *broken*) echo "claude-delete: can't restore, already there: x" >&2; exit 1;; esac\n`, { mode: 0o755 });
  const put = (name, m) => { fs.mkdirSync(path.join(bin, name)); fs.writeFileSync(path.join(bin, name, "manifest.json"), JSON.stringify(m)); };
  put("1_old", { id: "gone-1", title: "Test session", request: "setup", ticket: "Other", deleted_at: now - 7200, items: [{}, {}] });
  put("2_new", { id: "gone-2", title: "Other test", request: null, deleted_at: now - 60, items: [] });

  const fake = fakeVscode({ sessionsCommand: sessionsBin, openIn: "terminal" });
  const ctx = context();
  await load(fake).activate(ctx);
  await settle(ctx);
  const p = ctx.subscriptions[0].provider;
  const run = (name, el) => fake.commands.get("claudeWorksessions." + name)(el);

  let top = p.getChildren(undefined);
  const group = top.at(-1);
  assert.strictEqual(group.kind, "deleted");
  const gItem = p.getTreeItem(group);
  assert.deepStrictEqual([gItem.label, gItem.description, gItem.iconPath.id, gItem.collapsibleState, gItem.contextValue],
                         ["Deleted", "2", "trash", 1, "deleted-group"]);
  const kids = p.getChildren(group);
  const items = kids.map(k => p.getTreeItem(k));
  assert.deepStrictEqual(items.map(i => i.label), ["Other test", "Test session"]);                 // newest first
  assert.deepStrictEqual(items.map(i => i.description), ["work root · deleted 1m ago", "setup · deleted 2h ago"]);
  assert.deepStrictEqual([items[1].contextValue, items[1].iconPath.id], ["deleted", "history"]);
  assert.match(items[1].tooltip.value, /Test session.*deleted[\s\S]*setup · Other · 2 item\(s\) in the bin[\s\S]*gone-1/);
  assert.strictEqual(new Set(items.map(i => i.id)).size, 2);

  // search narrows it; no match hides the group
  p.setFilter("setup");
  assert.deepStrictEqual(p.getChildren(p.getChildren(undefined).at(-1)).map(k => k.m.id), ["gone-1"]);
  p.setFilter("nothing-like-this");
  assert.notStrictEqual(p.getChildren(undefined).at(-1)?.kind, "deleted");
  p.setFilter("");

  await run("restoreSession", kids[1]);
  assert.match(fs.readFileSync(log, "utf8"), /--restore gone-1/);
  assert.deepStrictEqual(fake.messages.at(-1), ["info", '"Test session" restored.']);
  await run("restoreSession", { m: { id: "broken", title: "B" } });
  assert.deepStrictEqual(fake.messages.at(-1), ["error", "claude-delete: can't restore, already there: x"]);

  fake.answers.push(undefined);                                                                    // cancel
  await run("purgeSession", kids[0]);
  assert.deepStrictEqual(fake.messages.at(-1), ["modal", 'Delete "Other test" for good?', "It leaves the bin and can't be restored."]);
  assert.doesNotMatch(fs.readFileSync(log, "utf8"), /--purge/);
  fake.answers.push("Delete for good");
  await run("purgeSession", kids[0]);
  assert.match(fs.readFileSync(log, "utf8"), /--purge gone-2 --yes/);
  fake.answers.push("Delete for good");
  await run("emptyBin");
  assert.deepStrictEqual(fake.messages.filter(m => m[0] === "modal").at(-1).slice(0, 2), ["modal", "Delete all 2 session(s) in the bin for good?"]);
  assert.match(fs.readFileSync(log, "utf8"), /--empty --yes/);
  fake.answers.push("Delete for good");
  await run("purgeSession", { m: { id: "broken", title: "B" } });
  assert.strictEqual(fake.messages.at(-1)[0], "error");

  // the bin watcher refreshes the tree
  assert.ok((fake.listeners["watch:*/manifest.json"] || []).length >= 2);
  for (const n of fs.readdirSync(bin)) fs.rmSync(path.join(bin, n), { recursive: true });
  fake.listeners["watch:*/manifest.json"].forEach(f => f());
  assert.notStrictEqual(p.getChildren(undefined).at(-1).kind, "deleted");
});

test("filters: the Filter menu sets day, tickets and artifacts; remembered; shown; cleared", async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cws-filt-"));
  const root = path.join(dir, "ws");
  const A = { path: path.join(root, "2026/09/23/10-00-00_a"), name: "demo", ticket: "BTPA-1", task_type: "", profile: "",
              files: [], files_truncated: false };
  const B = { path: path.join(root, "2026/09/01/10-00-00_b"), name: "old", ticket: "", task_type: "", profile: "",
              files: [], files_truncated: false };
  for (const r of [A, B]) fs.mkdirSync(r.path, { recursive: true });
  const now = Date.now() / 1000;
  const data = { work_root: root, sessions: [
    { id: "fresh", mtime: now - 60, started: now - 120, cwd: A.path, in_work_root: true, title: "Fresh", request: A, artifacts: ["/f"] },
    { id: "stale", mtime: now - 40 * 86400, started: now - 40 * 86400, cwd: B.path, in_work_root: true, title: "Stale", request: B, artifacts: [] },
  ] };
  const { bin } = stubSessions(dir, data);
  const binDir = process.env.CWS_TRASH_DIR;
  fs.mkdirSync(path.join(binDir, "x"), { recursive: true });
  fs.writeFileSync(path.join(binDir, "x", "manifest.json"), JSON.stringify({ id: "gone", title: "Gone", deleted_at: now }));
  const fake = fakeVscode({ sessionsCommand: bin, openIn: "terminal" });
  const ctx = context();
  await load(fake).activate(ctx);
  await settle(ctx);
  const view = ctx.subscriptions[0], p = view.provider;
  const sessions = () => allItems(p).filter(([c]) => c.kind === "session").map(([c]) => c.session.id);
  const pick = key => items => items.find(i => i.key === key);
  assert.deepStrictEqual(sessions(), ["fresh", "stale"]);
  assert.strictEqual(p.getChildren(undefined).at(-1).kind, "deleted");

  // Day → Today; Ticket → BTPA-1; Artifacts → With; then Esc
  fake.answers.push(pick("day"), items => items.find(i => i.k === "today"),
                    items => { assert.deepStrictEqual(items.map(i => i.description).slice(0, 2), ["Today", "Any ticket"]); return pick("ticket")(items); },
                    items => { assert.deepStrictEqual(items.map(i => i.label), ["BTPA-1", "(no ticket)"]); return [items[0]]; },
                    pick("artifacts"), items => items.find(i => i.k === "with"),
                    undefined);
  await fake.commands.get("claudeWorksessions.filter")();
  assert.deepStrictEqual(ctx.globalState.get("filters"), { day: { preset: "today" }, tickets: ["BTPA-1"], artifacts: "with" });
  assert.strictEqual(view.description, "By day · Last activity · only today · BTPA-1 · with artifacts");
  assert.ok(fake.executed.some(e => e[0] === "setContext" && e[1] === "claudeWorksessions.filtered"));
  assert.deepStrictEqual(sessions(), ["fresh"]);
  assert.notStrictEqual(p.getChildren(undefined).at(-1).kind, "deleted");                       // bin hidden while filtering

  // the menu shows current values and offers Clear; a date; cancelled sub-pickers change nothing
  fake.answers.push(items => {
    assert.deepStrictEqual(items.map(i => i.description), ["Today", "BTPA-1", "With artifacts", undefined]);
    return pick("day")(items);
  }, items => items.find(i => i.k === "date"), "2026-09-01",
  pick("ticket"), undefined,                     // cancel ticket picker
  pick("artifacts"), undefined,                  // cancel artifacts picker
  pick("day"), undefined,                        // cancel day picker
  pick("day"), items => items.find(i => i.k === "date"), undefined,   // cancel the date box
  pick("ticket"), () => [],                      // untick all: any ticket
  pick("artifacts"), items => items.find(i => i.k === "any"),
  undefined);
  await fake.commands.get("claudeWorksessions.filterActive")();
  assert.deepStrictEqual(ctx.globalState.get("filters"), { day: { preset: "date", date: "2026-09-01" }, tickets: [], artifacts: "any" });
  assert.deepStrictEqual(sessions(), []);                        // neither session was active on 2026-09-01
  assert.match(view.message, /No session matches the filters \(2026-09-01\)/);

  fake.answers.push(pick("clear"), undefined);
  await fake.commands.get("claudeWorksessions.filter")();
  assert.deepStrictEqual(ctx.globalState.get("filters"), { day: { preset: "any" }, tickets: [], artifacts: "any" });
  assert.strictEqual(view.description, "By day · Last activity");
  p.setFilters({ day: { preset: "any" }, tickets: ["BTPA-1"], artifacts: "any" });
  await fake.commands.get("claudeWorksessions.clearFilters")();
  assert.deepStrictEqual(sessions(), ["fresh", "stale"]);
  fs.rmSync(path.join(binDir, "x"), { recursive: true });
});
