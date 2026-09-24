#!/usr/bin/env zsh
# Remove what install.sh added to this machine. Your work root, _config, the
# Claude profile dirs and their history are NOT touched.
emulate -L zsh
REPO="${0:A:h}"
say() { print -r -- "  $*"; }
if [[ -x /usr/bin/python3 ]]; then PY=/usr/bin/python3; else PY="$(command -v python3)"; fi
for b in claude-audit claude-search claude-sessions claude-vscode claude-md-email claude-delete claude-hook-notfound claude-hook-vague claude-retro; do
  f="$HOME/.local/bin/$b"
  [[ -L "$f" && "$(readlink "$f")" == "$REPO/bin/$b" ]] && rm "$f" && say "removed $f"
done
if grep -qF "# >>> claude-worksessions >>>" "$HOME/.zshrc" 2>/dev/null; then
  cp -p "$HOME/.zshrc" "$HOME/.zshrc.bak-$(date +%Y%m%d-%H%M%S)"
  "$PY" - "$HOME/.zshrc" <<'PY'
import re, sys
p = sys.argv[1]; s = open(p).read()
s = re.sub(r"\n?# >>> claude-worksessions >>>.*?# <<< claude-worksessions <<<\n?", "\n", s, flags=re.S)
open(p, "w").write(s)
PY
  say "removed the block from ~/.zshrc (backup kept)"
fi
# VS Code: the Claude extension must stop launching through the claude-vscode just removed
for vsset in "$HOME/Library/Application Support/Code/User/settings.json" \
             "$HOME/.config/Code/User/settings.json" "$HOME/.vscode-server/data/Machine/settings.json"; do
  [[ -f "$vsset" ]] || continue
  out=$(WRAPPER="$HOME/.local/bin/claude-vscode" "$PY" - "$vsset" 2>&1 <<'PY'
import json, os, sys
p = sys.argv[1]
try:
    d = json.load(open(p))
except ValueError:
    print("unparsed"); raise SystemExit
if d.get("claudeCode.claudeProcessWrapper") == os.environ["WRAPPER"]:
    del d["claudeCode.claudeProcessWrapper"]
    open(p, "w").write(json.dumps(d, indent=4) + "\n")
    print("removed")
PY
  )
  case $out in
    removed)  say "removed claudeCode.claudeProcessWrapper from $vsset" ;;
    unparsed) say "remove claudeCode.claudeProcessWrapper from $vsset yourself (it has comments)" ;;
  esac
done
if command -v code >/dev/null 2>&1 &&
   code --list-extensions 2>/dev/null | grep -qix "jviegas6.claude-worksessions"; then
  code --uninstall-extension jviegas6.claude-worksessions >/dev/null 2>&1 && say "uninstalled the Work sessions sidebar"
fi
# The prompt-quality hooks: take their entries out of each profile's settings.json
for sfile in "$HOME"/.claude-*/settings.json(N); do
  out=$(BIN="$HOME/.local/bin" "$PY" - "$sfile" 2>&1 <<'PY'
import json, os, sys
p = sys.argv[1]
ours = {os.path.join(os.environ["BIN"], n) for n in ("claude-hook-notfound", "claude-hook-vague")}
try:
    d = json.load(open(p))
except ValueError:
    raise SystemExit
hooks, changed = d.get("hooks") or {}, False
for event in list(hooks):
    groups = []
    for g in hooks[event]:
        kept = [h for h in g.get("hooks", []) if h.get("command") not in ours]
        changed |= len(kept) != len(g.get("hooks", []))
        if kept:
            groups.append(dict(g, hooks=kept))
    if groups:
        hooks[event] = groups
    else:
        del hooks[event]
if changed:
    if hooks:
        d["hooks"] = hooks
    else:
        d.pop("hooks", None)
    open(p, "w").write(json.dumps(d, indent=2) + "\n")
    print("removed")
PY
  )
  [[ "$out" == removed ]] && say "removed the prompt-quality hooks from $sfile"
done
L="$HOME/.config/claude-worksessions/config.env"
[[ -L "$L" ]] && rm "$L" && say "removed $L (the config file itself is kept)"
say "Skills (~/.claude-*/skills/weekly-review, workday-recap) and ~/.config/yazi were left in place."
