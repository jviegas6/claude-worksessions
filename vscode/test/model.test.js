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
                         [["2026-09-22", 2], [M.ROOT_KEY, 1], ["2026-09-21", 1]]);
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
