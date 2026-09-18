#!/bin/zsh
# Remove what install.sh added to this machine. Your work root, _config, the
# Claude profile dirs and their history are NOT touched.
emulate -L zsh
REPO="${0:A:h}"
say() { print -r -- "  $*"; }
for b in claude-audit claude-search; do
  f="$HOME/.local/bin/$b"
  [[ -L "$f" && "$(readlink "$f")" == "$REPO/bin/$b" ]] && rm "$f" && say "removed $f"
done
if grep -qF "# >>> claude-worksessions >>>" "$HOME/.zshrc" 2>/dev/null; then
  cp -p "$HOME/.zshrc" "$HOME/.zshrc.bak-$(date +%Y%m%d-%H%M%S)"
  /usr/bin/python3 - "$HOME/.zshrc" <<'PY'
import re, sys
p = sys.argv[1]; s = open(p).read()
s = re.sub(r"\n?# >>> claude-worksessions >>>.*?# <<< claude-worksessions <<<\n?", "\n", s, flags=re.S)
open(p, "w").write(s)
PY
  say "removed the block from ~/.zshrc (backup kept)"
fi
L="$HOME/.config/claude-worksessions/config.env"
[[ -L "$L" ]] && rm "$L" && say "removed $L (the config file itself is kept)"
say "Skills (~/.claude-*/skills/weekly-review, workday-recap) and ~/.config/yazi were left in place."
