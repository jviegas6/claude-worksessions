#!/usr/bin/env python3
"""MCP servers for claude-worksessions: ask what you use, then configure Claude Code.

  python3 mcp/configure.py ask CONFIG.env                     ask the questions, save the answers
  python3 mcp/configure.py apply CONFIG.env PROFILE_DIR...    configure each profile's servers
  python3 mcp/configure.py show CONFIG.env                    what the answers select

The questions and the servers each answer brings come from mcp/catalog.json. Answers and the
values servers need (an organisation name, a workspace host) go in config.env as CWS_MCP_*;
nothing company-specific lives in the repo. Secrets (API tokens) are never written to
config.env: they are asked for when a server is first configured and kept only in the
profile's own .claude.json, which Claude Code keeps private (0600).

`apply` only touches servers named in the catalog: it adds or updates the selected ones and
removes catalog servers you no longer select. Servers you added by hand under other names
are left alone, and so are settings the catalog doesn't set on a server it manages (an
OAuth client id, extra headers, env).
"""

import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
CATALOG = os.path.join(HERE, "catalog.json")
PLACEHOLDER = re.compile(r"\{\{(secret:)?([a-z0-9_]+)\}\}")


def load_catalog(path=CATALOG):
    with open(path) as fh:
        return json.load(fh)


def read_config(path):
    """KEY="value" lines of config.env."""
    out = {}
    try:
        with open(path) as fh:
            for line in fh:
                m = re.match(r'^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$', line)
                if m:
                    out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def set_config(path, key, value):
    """Set KEY="value" in config.env, replacing an existing line or appending one."""
    line = '{}="{}"'.format(key, value.replace('"', '\\"'))
    try:
        with open(path) as fh:
            text = fh.read()
    except OSError:
        text = ""
    if re.search(r"(?m)^{}=".format(re.escape(key)), text):
        text = re.sub(r"(?m)^{}=.*$".format(re.escape(key)), lambda m: line, text)
    else:
        text += ("" if text.endswith("\n") or not text else "\n") + line + "\n"
    with open(path, "w") as fh:
        fh.write(text)


def input_key(name):
    return "CWS_MCP_" + name.upper()


def answers(catalog, config):
    """{question key: [choice ids]} from config.env; None where a question is unanswered."""
    out = {}
    for q in catalog["questions"]:
        raw = config.get(q["key"])
        out[q["key"]] = None if raw is None else [c for c in raw.split() if c]
    return out


def selected(catalog, config):
    """(server names, notes) the saved answers select, in catalog order. Notes are what to set
    up outside Claude Code: claude.ai connectors, and instructions (a vendor's plugin, a
    server your admins host), each once."""
    names, notes = [], []
    got = answers(catalog, config)
    for q in catalog["questions"]:
        for choice in q["choices"]:
            if choice["id"] in (got[q["key"]] or []):
                names += [s for s in choice.get("servers", []) if s not in names]
                for note in (["connect in claude.ai (Settings > Connectors): " + choice["connector"]]
                             if choice.get("connector") else []) + ([choice["note"]] if choice.get("note") else []):
                    if note not in notes:
                        notes.append(note)
    return names, notes


def inputs_needed(catalog, names):
    """The non-secret placeholders the selected servers use: {name: prompt}."""
    need = {}
    for n in names:
        for secret, key in PLACEHOLDER.findall(json.dumps(catalog["servers"][n]["config"])):
            if not secret and key not in ("repo", "npx", "python"):
                need[key] = catalog.get("inputs", {}).get(key, key)
    return need


def secrets_needed(server):
    return [key for secret, key in PLACEHOLDER.findall(json.dumps(server["config"])) if secret]


# --- ask --------------------------------------------------------------------------------
def ask(catalog, config_path, read=None, write=print):
    """Ask each question (the saved answer is the default) and any values the chosen servers
    need, and save them to config.env."""
    read = read or input
    config = read_config(config_path)
    got = answers(catalog, config)
    write("Which tools do you use? Claude gets a connection (MCP server) for each.")
    for q in catalog["questions"]:
        choices = q["choices"]
        write("")
        write(q["ask"] + ("  (several: numbers separated by spaces)" if q.get("multi") else ""))
        for i, c in enumerate(choices, 1):
            write("  {}) {}".format(i, c["label"]))
        current = got[q["key"]]
        default = " ".join(str(i) for i, c in enumerate(choices, 1) if c["id"] in (current or [])) or \
            str(next(i for i, c in enumerate(choices, 1) if c["id"] == "none"))
        while True:
            raw = read("  [{}]: ".format(default)).strip() or default
            picks = raw.replace(",", " ").split()
            if all(p.isdigit() and 1 <= int(p) <= len(choices) for p in picks) and picks and \
                    (q.get("multi") or len(picks) == 1):
                break
            write("  pick {} from the list".format("numbers" if q.get("multi") else "one number"))
        ids = [choices[int(p) - 1]["id"] for p in picks]
        if len(ids) > 1:
            ids = [i for i in ids if i != "none"]
        set_config(config_path, q["key"], " ".join(ids))
    names, _ = selected(catalog, read_config(config_path))
    config = read_config(config_path)
    for key, prompt in inputs_needed(catalog, names).items():
        current = config.get(input_key(key), "")
        while True:
            value = read("{}{}: ".format(prompt, " [{}]".format(current) if current else "")).strip() or current
            if value:
                break
            write("  needed by a server you chose")
        set_config(config_path, input_key(key), value)
    return names


# --- apply ------------------------------------------------------------------------------
def fill(value, values):
    """Replace {{key}} / {{secret:key}} placeholders, recursively; None if one is missing."""
    if isinstance(value, dict):
        out = {k: fill(v, values) for k, v in value.items()}
        return None if any(v is None for v in out.values()) else out
    if isinstance(value, list):
        out = [fill(v, values) for v in value]
        return None if any(v is None for v in out) else out
    if isinstance(value, str):
        missing = [k for _, k in PLACEHOLDER.findall(value) if values.get(k) in (None, "")]
        if missing:
            return None
        return PLACEHOLDER.sub(lambda m: values[m.group(2)], value)
    return value


def existing_secrets(server, current):
    """Secret values already configured for a server, found by matching the catalog config's
    shape against what the profile has: {secret key: value}."""
    found = {}
    if not current:
        return found

    def walk(want, have):
        if isinstance(want, dict) and isinstance(have, dict):
            for k, v in want.items():
                walk(v, have.get(k))
        elif isinstance(want, list) and isinstance(have, list):
            for a, b in zip(want, have):
                walk(a, b)
        elif isinstance(want, str) and isinstance(have, str):
            m = re.fullmatch(r"(.*)\{\{secret:([a-z0-9_]+)\}\}(.*)", want)
            if m and have.startswith(m.group(1)) and have.endswith(m.group(3)) and \
                    len(have) > len(m.group(1)) + len(m.group(3)):
                found[m.group(2)] = have[len(m.group(1)):len(have) - len(m.group(3)) or None]
    walk(server["config"], current)
    return found


def merge(have, want):
    """The catalog's settings over what the profile has: keys the catalog sets are replaced,
    keys it doesn't know (an oauth client id, extra headers, env) are kept."""
    if not isinstance(have, dict) or not isinstance(want, dict):
        return want
    out = dict(have)
    for k, v in want.items():
        out[k] = merge(have.get(k), v) if isinstance(v, dict) else v
    return out


def tool_paths():
    return {"repo": os.path.dirname(HERE), "npx": shutil.which("npx") or "npx",
            "python": shutil.which("python3") or "python3"}


def plan(catalog, config, current, ask_secret=None):
    """The mcpServers a profile should have: (new mcpServers, changes, skipped)."""
    names, _ = selected(catalog, config)
    values = dict(tool_paths())
    values.update({k[len("CWS_MCP_"):].lower(): v for k, v in config.items() if k.startswith("CWS_MCP_")})
    new, changes, skipped = dict(current), [], []
    for name in catalog["servers"]:
        if name not in names:
            if name in new:
                del new[name]
                changes.append("removed " + name)
            continue
        server = catalog["servers"][name]
        vals = dict(values)
        vals.update(existing_secrets(server, current.get(name)))
        for key in secrets_needed(server):
            if not vals.get(key) and ask_secret:
                vals[key] = ask_secret(name, key, catalog.get("inputs", {}).get(key, key))
        cfg = fill(server["config"], vals)
        if cfg is None:
            skipped.append(name)
            continue
        cfg = merge(current.get(name), cfg)
        if current.get(name) != cfg:
            changes.append(("updated " if name in current else "added ") + name)
            new[name] = cfg
    return new, changes, skipped


def apply(catalog, config_path, profile_dirs, dry=False, ask_secret=None, write=print):
    config = read_config(config_path)
    names, notes = selected(catalog, config)
    if all(v is None for v in answers(catalog, config).values()):
        write("MCP servers: not set up yet -- run ./install.sh --mcp to choose them")
        return 0
    for pdir in profile_dirs:
        path = os.path.join(pdir, ".claude.json")
        try:
            with open(path) as fh:
                data = json.load(fh)
        except FileNotFoundError:
            data = {}
        except ValueError:
            write("{}: {} isn't valid JSON -- MCP servers left alone".format(os.path.basename(pdir), path))
            continue
        current = data.get("mcpServers") or {}
        new, changes, skipped = plan(catalog, config, current, ask_secret)
        label = os.path.basename(pdir).replace(".claude-", "")
        for name in skipped:
            write("{}: {} needs a value that wasn't given -- skipped (./install.sh --mcp)".format(label, name))
        if not changes:
            write("{}: MCP servers up to date ({})".format(label, ", ".join(n for n in names if n in new) or "none"))
            continue
        write("{}: {}{}".format(label, "[dry-run] " if dry else "", "; ".join(changes)))
        if dry:
            continue
        data["mcpServers"] = new
        if os.path.exists(path):
            shutil.copy2(path, path + ".bak-mcp")          # the file holds much more than servers
        mode = os.stat(path).st_mode & 0o777 if os.path.exists(path) else 0o600
        tmp = path + ".cws-tmp"
        with open(tmp, "w") as fh:
            json.dump(data, fh, indent=2)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    for note in notes:
        write(note)
    return 0


def show(catalog, config_path, write=print):
    config = read_config(config_path)
    got = answers(catalog, config)
    for q in catalog["questions"]:
        labels = [c["label"] for c in q["choices"] if c["id"] in (got[q["key"]] or [])]
        write("{:<34} {}".format(q["ask"], ", ".join(labels) if got[q["key"]] is not None else "(not answered)"))
    names, notes = selected(catalog, config)
    write("servers: " + (", ".join(names) or "none"))
    for note in notes:
        write(note)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2 or argv[0] not in ("ask", "apply", "show") or (argv[0] == "apply" and len(argv) < 3 and "--dry-run" not in argv):
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    catalog = load_catalog()
    cmd, config_path = argv[0], argv[1]
    if cmd == "ask":
        ask(catalog, config_path)
        return 0
    if cmd == "show":
        show(catalog, config_path)
        return 0
    rest = argv[2:]
    dry, yes = "--dry-run" in rest, "--yes" in rest
    dirs = [a for a in rest if not a.startswith("--")]

    def ask_secret(server, key, prompt):
        if yes or dry or not sys.stdin.isatty():
            return None
        import getpass
        return getpass.getpass("  {} ({}), Enter to skip: ".format(prompt, server)).strip() or None

    return apply(catalog, config_path, dirs, dry=dry, ask_secret=ask_secret)


if __name__ == "__main__":
    sys.exit(main())
