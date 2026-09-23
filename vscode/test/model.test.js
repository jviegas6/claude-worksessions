// node --test vscode/test — run from tests/test_vscode.py as part of pytest.
const test = require("node:test");
const assert = require("node:assert");
const M = require("../model");

const ROOT = "/w";
const req = (p, extra = {}) => ({ path: `${ROOT}/${p}`, name: p.split("/").pop(), ticket: "", task_type: "",
                                  profile: "", ...extra });
const ses = (id, mtime, request, extra = {}) => ({ id, mtime, cwd: request ? request.path : ROOT,
  in_work_root: true, title: "t-" + id, first_prompt: "f", last_prompt: "l", request, ...extra });

const A = req("2026/09/22/10-00-00_a", { ticket: "BTPA-1", profile: "work" });
const B = req("2026/09/22/11-00-00_b", { ticket: "Other" });
const C = req("2026/09/21/09-00-00_c", { ticket: "BTPA-1" });
const data = {
  work_root: ROOT,
  sessions: [
    ses("a1", 100, A), ses("a2", 500, A), ses("b1", 300, B), ses("c1", 50, C),
    ses("root", 400, null),
    ses("empty", 600, B, { title: null, first_prompt: null, last_prompt: null }),
    ses("outside", 700, null, { in_work_root: false, cwd: "/repo" }),
  ],
};

test("visible drops empty and outside sessions unless asked", () => {
  assert.deepStrictEqual(M.visible(data).map(s => s.id), ["a1", "a2", "b1", "c1", "root"]);
  assert.ok(M.visible(data, { showEmpty: true }).some(s => s.id === "empty"));
});

test("requests are newest first, with the work root as a pseudo-request", () => {
  const rs = M.requests(data);
  assert.deepStrictEqual(rs.map(r => r.name), ["10-00-00_a", "Work root — no request folder", "11-00-00_b", "09-00-00_c"]);
  assert.deepStrictEqual(rs[0].sessions.map(s => s.id), ["a2", "a1"]);
  assert.strictEqual(rs[0].mtime, 500);
  assert.strictEqual(rs[1].root, true);
  assert.strictEqual(rs[1].path, ROOT);
});

test("grouping by day", () => {
  const g = M.tree(data, "day");
  assert.deepStrictEqual(g.map(x => [x.key, x.requests.length]),
                         [["2026-09-22", 2], ["2026-09-21", 1], [M.ROOT_KEY, 1]]);   // days newest first, root last
});

test("grouping by ticket", () => {
  const g = M.tree(data, "ticket");
  assert.deepStrictEqual(g.map(x => [x.key, x.requests.map(r => r.name)]),
    [["BTPA-1", ["10-00-00_a", "09-00-00_c"]], [M.ROOT_KEY, ["Work root — no request folder"]], ["Other", ["11-00-00_b"]]]);
  const none = { work_root: ROOT, sessions: [ses("x", 1, req("2026/01/01/x"))] };
  assert.strictEqual(M.tree(none, "ticket")[0].key, "(no ticket)");
});

test("recent is a flat list with each session's request", () => {
  const t = M.tree(data, "recent");
  assert.deepStrictEqual(t.map(x => x.session.id), ["a2", "root", "b1", "a1", "c1"]);
  assert.strictEqual(t[0].request.name, "10-00-00_a");
  assert.ok(t.every(x => x.showRequest));
});

test("dayOf handles requests outside the dated layout", () => {
  assert.strictEqual(M.dayOf({ root: false, path: "/elsewhere/repo" }, ROOT), "(elsewhere)");
});

test("labels and tab names", () => {
  assert.strictEqual(M.sessionLabel({ id: "abcdefghij", title: "T" }), "T");
  assert.strictEqual(M.sessionLabel({ id: "abcdefghij", first_prompt: "F" }), "F");
  assert.strictEqual(M.sessionLabel({ id: "abcdefghij", last_prompt: "L" }), "L");
  assert.strictEqual(M.sessionLabel({ id: "abcdefghij" }), "abcdefgh");
  assert.strictEqual(M.tabName({ ticket: "BTPA-1" }, "x"), "BTPA-1 · x");
  assert.strictEqual(M.tabName({ ticket: "Other" }, "x"), "x");
  assert.strictEqual(M.tabName(null, "x"), "x");
});

test("ago", () => {
  assert.strictEqual(M.ago(1000, 1010), "1m");
  assert.strictEqual(M.ago(0, 7200), "2h");
  assert.strictEqual(M.ago(0, 3 * 86400), "3d");
  assert.strictEqual(M.ago(100, 50), "1m");
});

test("pending tabs take the first new session that belongs to them", () => {
  const known = new Set(data.sessions.map(s => s.id));
  const D = req("2026/09/22/12-00-00_d");
  const later = {
    work_root: ROOT,
    sessions: [...data.sessions, ses("a3", 900, A), ses("a4", 950, A), ses("d1", 910, D), ses("d0", 10, D)],
  };
  const pending = [
    { key: "into-a", kind: "request", dir: A.path, since: 800, knownRequests: new Set(), knownSessions: known },
    { key: "into-a-too", kind: "request", dir: A.path, since: 800, knownRequests: new Set(), knownSessions: known },
    { key: "new", kind: "new", dir: ROOT, since: 800,
      knownRequests: new Set([A.path, B.path, C.path, ROOT]), knownSessions: known },
    { key: "nothing-yet", kind: "request", dir: C.path, since: 800, knownRequests: new Set(), knownSessions: known },
  ];
  const got = M.matchPending(pending, later, ["a4-was-already-open"]);
  assert.deepStrictEqual(got.map(m => [m.key, m.session.id, m.request.path]),
    [["into-a", "a3", A.path], ["into-a-too", "a4", A.path], ["new", "d1", D.path]]);
  // a session already linked to a tab is not taken again
  assert.deepStrictEqual(M.matchPending(pending.slice(0, 1), later, ["a3"]).map(m => m.session.id), ["a4"]);
});

test("the search box matches every word anywhere in a session or its request", () => {
  const s = ses("abc123", 1, A, { title: "Fix the firewall", last_prompt: "open port 443" });
  assert.ok(M.matches(s, ""));
  assert.ok(M.matches(s, "FIREWALL 443"));
  assert.ok(M.matches(s, "btpa-1 work"));            // ticket and profile
  assert.ok(M.matches(s, "10-00-00_a abc1"));         // folder and id
  assert.ok(!M.matches(s, "firewall 80"));
  assert.deepStrictEqual(M.visible(data, { filter: "t-a" }).map(x => x.id), ["a1", "a2"]);
  assert.deepStrictEqual(M.tree(data, "day", { filter: "11-00-00_b" }).map(g => g.key), ["2026-09-22"]);
});

test("parseCsv handles quotes, commas, newlines and CRLF", () => {
  const rows = M.parseCsv('a,b,c\r\n1,"x, ""y""",\n2,"multi\nline",z\n\n');
  assert.deepStrictEqual(rows, [{ a: "1", b: 'x, "y"', c: "" }, { a: "2", b: "multi\nline", c: "z" }]);
  assert.deepStrictEqual(M.parseCsv(""), []);
  assert.deepStrictEqual(M.parseCsv("a,b\n1"), [{ a: "1", b: "" }]);
});

test("task types: used ones first, then seeds, no repeats", () => {
  const d = { work_root: ROOT, sessions: [ses("x", 2, req("2026/01/02/x", { task_type: "security" })),
                                         ses("y", 1, req("2026/01/01/y", { task_type: "tooling" }))] };
  assert.deepStrictEqual(M.taskTypes(d, "permissions, tooling,  ,support"),
                         ["security", "tooling", "permissions", "support"]);
  assert.deepStrictEqual(M.taskTypes(d), ["security", "tooling"]);
});

test("setTaskType writes the session override or the folder default", () => {
  const fs = require("fs"), os = require("os"), path = require("path");
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cws-type-"));
  fs.writeFileSync(path.join(dir, ".session.json"), JSON.stringify({ name: "n", task_type: "tooling" }));
  assert.deepStrictEqual(M.setTaskType(dir, "s1", "security"), ["tooling", "security"]);
  assert.deepStrictEqual(M.setTaskType(dir, "s1", "permissions"), ["security", "permissions"]);
  assert.deepStrictEqual(M.setTaskType(dir, null, "support"), ["tooling", "support"]);
  const d = JSON.parse(fs.readFileSync(path.join(dir, ".session.json"), "utf8"));
  assert.deepStrictEqual(d, { name: "n", task_type: "support", session_types: { s1: "permissions" } });
  fs.writeFileSync(path.join(dir, ".session.json"), JSON.stringify({ session_types: "junk" }));
  assert.deepStrictEqual(M.setTaskType(dir, "s2", "x"), ["", "x"]);
});

test("readSkills reads frontmatter, first dir wins, skips folders without SKILL.md", () => {
  const fs = require("fs"), os = require("os"), path = require("path");
  const a = fs.mkdtempSync(path.join(os.tmpdir(), "cws-sk-")), b = fs.mkdtempSync(path.join(os.tmpdir(), "cws-sk-"));
  const put = (dir, n, body) => { fs.mkdirSync(path.join(dir, n)); if (body !== null) fs.writeFileSync(path.join(dir, n, "SKILL.md"), body); };
  put(a, "weekly-review", "---\nname: weekly-review\ndescription: Fill in the tracker\n---\nbody");
  put(a, "quoted", '---\nname: quoted\ndescription: "Has: a colon"\n---\n');
  put(a, "bare", "no frontmatter");
  put(a, "empty", null);
  put(b, "weekly-review", "---\nname: weekly-review\ndescription: other copy\n---\n");
  put(b, "only-b", "---\ndescription: from b\n---\n");
  assert.deepStrictEqual(M.readSkills([a, b, "/does/not/exist"]), [
    { name: "bare", description: "" },
    { name: "quoted", description: "Has: a colon" },
    { name: "weekly-review", description: "Fill in the tracker" },
    { name: "only-b", description: "from b" },
  ]);
});

test("auditArgs", () => {
  assert.deepStrictEqual(M.auditArgs("today"), ["--day"]);
  assert.deepStrictEqual(M.auditArgs("week", true), ["--week", "--detail"]);
  assert.deepStrictEqual(M.auditArgs("lastweek", false, "2026-09-15"), ["--week", "2026-09-15"]);
  assert.deepStrictEqual(M.auditArgs("month"), ["--month"]);
  assert.deepStrictEqual(M.auditArgs("day", true, "2026-09-01"), ["--day", "2026-09-01", "--detail"]);
  assert.deepStrictEqual(M.auditArgs("weekof", false, "2026-09-01"), ["--week", "2026-09-01"]);
  assert.deepStrictEqual(M.auditArgs("nonsense"), []);
});

test("files: search matches file names, shownFiles narrows, fileChildren builds one level", () => {
  const files = ["notes.md", "b/script.py", "b/c/out.csv", "b/c/brainlabs.csv", "a/x.txt"];
  const s = ses("f1", 1, { ...A, files });
  assert.ok(M.matches(s, "brainlabs csv"));
  assert.ok(!M.matches(s, "nothing-like-it"));
  assert.ok(M.matches(ses("f2", 1, A), "t-f2"));                        // requests without files
  assert.deepStrictEqual(M.shownFiles(files, ""), files);
  assert.deepStrictEqual(M.shownFiles(files, "BRAINLABS zzz"), ["b/c/brainlabs.csv"]);
  assert.deepStrictEqual(M.shownFiles(files, "t-f1"), files);           // no file matches: all
  assert.deepStrictEqual(M.shownFiles(undefined, "x"), []);
  assert.deepStrictEqual(M.fileChildren(files), [
    { kind: "dir", name: "a", prefix: "a/" }, { kind: "dir", name: "b", prefix: "b/" },
    { kind: "file", rel: "notes.md" }]);
  assert.deepStrictEqual(M.fileChildren(files, "b/"), [
    { kind: "dir", name: "c", prefix: "b/c/" }, { kind: "file", rel: "b/script.py" }]);
  assert.deepStrictEqual(M.fileChildren(files, "b/c/").map(x => x.rel), ["b/c/brainlabs.csv", "b/c/out.csv"]);
});

test("sorting: last activity, started, or name — days stay newest first", () => {
  const P = req("2026/09/20/08-00-00_p", { name: "Zeta", started: 100 });
  const Q = req("2026/09/22/09-00-00_q", { name: "alpha", started: 300 });
  const R = req("2026/09/22/10-00-00_r", { name: "Beta", started: 0 });   // no start: its sessions'
  const d = { work_root: ROOT, sessions: [
    ses("p1", 900, P, { started: 110, title: "old one resumed" }),        // oldest, but active last
    ses("q1", 400, Q, { started: 310, title: "b session" }),
    ses("q2", 350, Q, { started: 320, title: "A session" }),
    ses("r1", 500, R, { title: "no start" }),                            // falls back to mtime
  ] };
  const names = sort => M.requests(d, { sort }).map(r => r.name);
  assert.deepStrictEqual(names(), ["Zeta", "Beta", "alpha"]);            // default: last activity
  assert.deepStrictEqual(names("activity"), ["Zeta", "Beta", "alpha"]);
  assert.deepStrictEqual(names("started"), ["Beta", "alpha", "Zeta"]);   // Beta: 500 from its session
  assert.deepStrictEqual(names("name"), ["alpha", "Beta", "Zeta"]);
  assert.deepStrictEqual(names("bogus"), names("activity"));
  const q = sort => M.requests(d, { sort }).find(r => r.name === "alpha").sessions.map(s => s.id);
  assert.deepStrictEqual([q("activity"), q("started"), q("name")], [["q1", "q2"], ["q2", "q1"], ["q2", "q1"]]);
  assert.strictEqual(M.requests(d, { sort: "name" }).find(r => r.name === "alpha").mtime, 400);
  assert.deepStrictEqual(M.tree(d, "recent", { sort: "started" }).map(x => x.session.id), ["r1", "q2", "q1", "p1"]);
  assert.deepStrictEqual(M.tree(d, "recent", { sort: "name" }).map(x => x.session.id), ["q2", "q1", "r1", "p1"]);
  assert.deepStrictEqual(M.tree(d, "recent").map(x => x.session.id), ["p1", "r1", "q1", "q2"]);
  // days: newest first whatever the sort; requests within a day follow it
  for (const sort of M.SORTS) assert.deepStrictEqual(M.tree(d, "day", { sort }).map(g => g.key), ["2026-09-22", "2026-09-20"]);
  assert.deepStrictEqual(M.tree(d, "day", { sort: "name" })[0].requests.map(r => r.name), ["alpha", "Beta"]);
  // tickets follow the sort
  const t = { work_root: ROOT, sessions: [ses("x", 9, req("2026/01/01/x", { ticket: "ZZ-1", name: "x" })),
                                           ses("y", 1, req("2026/01/02/y", { ticket: "AA-1", name: "y" }))] };
  assert.deepStrictEqual(M.tree(t, "ticket").map(g => g.key), ["ZZ-1", "AA-1"]);
  assert.deepStrictEqual(M.tree(t, "ticket", { sort: "name" }).map(g => g.key), ["ZZ-1", "AA-1"]);   // requests x, y by name
});

test("pins: stored in the work root, toggled, and shown first", () => {
  const fs = require("fs"), os = require("os"), path = require("path");
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "cws-pins-"));
  assert.deepStrictEqual(M.readPins(root), { sessions: {}, requests: {} });   // no file
  fs.mkdirSync(path.join(root, "_config"));
  fs.writeFileSync(path.join(root, "_config", "pinned.json"), "{bad");
  assert.deepStrictEqual(M.readPins(root), { sessions: {}, requests: {} });
  fs.writeFileSync(path.join(root, "_config", "pinned.json"), JSON.stringify({ sessions: ["x"], requests: null }));
  assert.deepStrictEqual(M.readPins(root), { sessions: {}, requests: {} });

  const R = { path: path.join(root, "2026/09/22/10-00-00_r"), name: "R", ticket: "", task_type: "", profile: "" };
  assert.strictEqual(M.togglePin(root, "session", "s1", 100), true);
  assert.strictEqual(M.togglePin(root, "request", R.path, 200), true);
  assert.deepStrictEqual(M.readPins(root), { sessions: { s1: 100 }, requests: { "2026/09/22/10-00-00_r": 200 } });
  assert.strictEqual(M.togglePin(root, "session", "s1"), false);
  assert.deepStrictEqual(M.readPins(root).sessions, {});
  const fresh = fs.mkdtempSync(path.join(os.tmpdir(), "cws-pins-"));      // creates _config
  M.togglePin(fresh, "session", "z");
  assert.ok(fs.existsSync(path.join(fresh, "_config", "pinned.json")));

  const S = { path: path.join(root, "2026/09/21/09-00-00_s"), name: "S", ticket: "", task_type: "", profile: "" };
  const d = { work_root: root, sessions: [
    { id: "r1", mtime: 50, cwd: R.path, in_work_root: true, title: "in R", request: R },
    { id: "s1", mtime: 90, cwd: S.path, in_work_root: true, title: "alpha", request: S },
    { id: "s2", mtime: 80, cwd: S.path, in_work_root: true, title: "Beta", request: S },
    { id: "root", mtime: 70, cwd: root, in_work_root: true, title: "at root", request: null },
  ] };
  const pins = { sessions: { s2: 1, s1: 2, gone: 3, root: 4 }, requests: { "2026/09/22/10-00-00_r": 1 } };
  assert.ok(M.isPinnedSession(pins, "s1") && !M.isPinnedSession(pins, "r1") && !M.isPinnedSession(null, "s1"));
  assert.ok(M.isPinnedRequest(pins, root, R) && !M.isPinnedRequest(pins, root, S));
  assert.ok(!M.isPinnedRequest(pins, root, { root: true, path: root }) && !M.isPinnedRequest(undefined, root, R));
  const p = M.pinned(d, pins, {});
  assert.deepStrictEqual(p.requests.map(r => r.name), ["R"]);
  assert.deepStrictEqual(p.sessions.map(x => x.session.id), ["s1", "s2", "root"]);   // missing "gone" skipped
  assert.strictEqual(p.sessions[0].request.name, "S");
  assert.deepStrictEqual(M.pinned(d, pins, { sort: "name" }).sessions.map(x => x.session.id), ["s1", "root", "s2"]);
  assert.deepStrictEqual(M.pinned(d, pins, { filter: "beta" }).sessions.map(x => x.session.id), ["s2"]);

  for (const g of M.GROUPINGS) {
    const t = M.tree(d, g, { pins });
    assert.strictEqual(t[0].kind, "pinned");
    assert.strictEqual(t[1].kind, g === "recent" ? "session" : "group");
  }
  assert.notStrictEqual(M.tree(d, "day", { pins: { sessions: {}, requests: {} } })[0].kind, "pinned");
  assert.notStrictEqual(M.tree(d, "day", { pins, filter: "nothing matches" })[0]?.kind, "pinned");
  assert.notStrictEqual(M.tree(d, "day")[0].kind, "pinned");                        // no pins given
});

test("the deleted-sessions bin: where it is, and what is in it", () => {
  const fs = require("fs"), os = require("os"), path = require("path");
  assert.strictEqual(M.binDir({ CWS_TRASH_DIR: "/b" }, "/h"), "/b");
  assert.strictEqual(M.binDir({ XDG_DATA_HOME: "/x" }, "/h"), "/x/claude-worksessions/trash");
  assert.strictEqual(M.binDir({}, "/h"), "/h/.local/share/claude-worksessions/trash");
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cws-bin-model-"));
  assert.deepStrictEqual(M.readDeleted(path.join(dir, "missing")), []);
  const put = (name, m) => { fs.mkdirSync(path.join(dir, name)); if (m !== undefined) fs.writeFileSync(path.join(dir, name, "manifest.json"), typeof m === "string" ? m : JSON.stringify(m)); };
  put("a", { id: "s-old", title: "Old test", request: "demo", deleted_at: 100 });
  put("b", { id: "s-new", title: "Newer", ticket: "BTPA-1", deleted_at: 200 });
  put("c", { id: "s-none", title: "No date" });
  put("d", "{bad"); put("e", { title: "no id" }); put("f");
  const all = M.readDeleted(dir);
  assert.deepStrictEqual(all.map(m => m.id), ["s-new", "s-old", "s-none"]);
  assert.strictEqual(all[0].dir, path.join(dir, "b"));
  assert.deepStrictEqual(M.readDeleted(dir, "demo old").map(m => m.id), ["s-old"]);
  assert.deepStrictEqual(M.readDeleted(dir, "btpa-1").map(m => m.id), ["s-new"]);
});

test("filters: day ranges, tickets, artifacts, and how they combine", () => {
  const T = (y, mo, d, h = 0) => new Date(y, mo - 1, d, h).getTime() / 1000;
  const now = T(2026, 9, 23, 12);                                   // Wednesday
  assert.strictEqual(M.dayRange(null, now), null);
  assert.strictEqual(M.dayRange({ preset: "any" }, now), null);
  assert.deepStrictEqual(M.dayRange({ preset: "today" }, now), [T(2026, 9, 23), T(2026, 9, 24)]);
  assert.deepStrictEqual(M.dayRange({ preset: "yesterday" }, now), [T(2026, 9, 22), T(2026, 9, 23)]);
  assert.deepStrictEqual(M.dayRange({ preset: "last7" }, now), [T(2026, 9, 17), T(2026, 9, 24)]);
  assert.deepStrictEqual(M.dayRange({ preset: "thisweek" }, now), [T(2026, 9, 21), T(2026, 9, 28)]);
  assert.deepStrictEqual(M.dayRange({ preset: "lastweek" }, now), [T(2026, 9, 14), T(2026, 9, 21)]);
  assert.deepStrictEqual(M.dayRange({ preset: "thismonth" }, now), [T(2026, 9, 1), T(2026, 10, 1)]);
  assert.deepStrictEqual(M.dayRange({ preset: "date", date: "2026-09-02" }, now), [T(2026, 9, 2), T(2026, 9, 3)]);
  assert.strictEqual(M.dayRange({ preset: "date", date: "02/09" }, now), null);
  assert.strictEqual(M.dayRange({ preset: "nonsense" }, now), null);
  assert.deepStrictEqual(M.dayRange({ preset: "thisweek" }, T(2026, 9, 27, 9))[0], T(2026, 9, 21));   // Sunday: same week
  assert.ok(Array.isArray(M.dayRange({ preset: "today" })));                                       // defaults to now

  const R = req("2026/09/22/10-00-00_r", { ticket: "BTPA-1" });
  const d = { work_root: ROOT, sessions: [
    ses("span", T(2026, 9, 23, 9), R, { started: T(2026, 9, 22, 17), artifacts: ["/x"] }),   // 22nd → 23rd
    ses("old", T(2026, 9, 2, 10), R, { started: T(2026, 9, 2, 9), artifacts: [] }),
    ses("root", T(2026, 9, 23, 8), null, { written: ["/y"] }),
    ses("other", T(2026, 9, 22, 8), req("2026/09/22/08-00-00_o", { ticket: "Other" })),
  ] };
  const ids = filters => M.visible(d, { filters, now }).map(s => s.id);
  assert.deepStrictEqual(ids(null), ["span", "old", "root", "other"]);
  assert.deepStrictEqual(ids({ day: { preset: "today" } }), ["span", "root"]);
  assert.deepStrictEqual(ids({ day: { preset: "yesterday" } }), ["span", "other"]);              // active on both days
  assert.deepStrictEqual(ids({ day: { preset: "date", date: "2026-09-02" } }), ["old"]);
  assert.deepStrictEqual(ids({ tickets: ["BTPA-1"] }), ["span", "old"]);
  assert.deepStrictEqual(ids({ tickets: [M.NO_TICKET, "Other"] }), ["root", "other"]);
  assert.deepStrictEqual(ids({ artifacts: "with" }), ["span", "root"]);
  assert.deepStrictEqual(ids({ artifacts: "without" }), ["old", "other"]);
  assert.deepStrictEqual(ids({ day: { preset: "today" }, tickets: ["BTPA-1"], artifacts: "with" }), ["span"]);
  assert.deepStrictEqual(ids({ tickets: [] }), ids(null));

  assert.ok(!M.filtersActive(null) && !M.filtersActive({ day: { preset: "any" }, tickets: [], artifacts: "any" }));
  assert.ok(M.filtersActive({ artifacts: "with" }) && M.filtersActive({ tickets: ["X"] }) && M.filtersActive({ day: { preset: "today" } }));
  assert.strictEqual(M.describeFilters({ day: { preset: "any" } }), "");
  assert.strictEqual(M.describeFilters({ day: { preset: "lastweek" }, tickets: ["A-1", "B-2"], artifacts: "without" }),
                     "last week · A-1, B-2 · without artifacts");
  assert.strictEqual(M.describeFilters({ day: { preset: "date", date: "2026-09-02" }, tickets: ["A", "B", "C"] }),
                     "2026-09-02 · 3 tickets");
  assert.deepStrictEqual(M.ticketsInUse(d), ["BTPA-1", "Other", M.NO_TICKET]);
  // pins and groups follow the filters
  assert.deepStrictEqual(M.tree(d, "day", { filters: { tickets: ["Other"] } }).map(g => g.key), ["2026-09-22"]);
});
