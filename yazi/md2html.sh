#!/usr/bin/env zsh
PATH="/opt/homebrew/bin:/usr/local/bin:/home/linuxbrew/.linuxbrew/bin:$PATH"
# Render a Markdown file to styled HTML and open it in the default browser (for copy → email)
src="$1"; out="${TMPDIR:-/tmp}/md-email"; mkdir -p "$out"
html="$out/${${src:t}:r}.html"
pandoc "$src" -f gfm -t html5 -s --metadata title="${${src:t}:r}" \
  -H "$HOME/.config/yazi/md-email.css" -o "$html" || exit 1
if [[ "$(uname -s)" == Darwin ]]; then open "$html"
elif grep -qsi microsoft /proc/version; then        # WSL: the Windows browser
  if command -v wslview >/dev/null; then wslview "$html"
  else (cd /mnt/c && explorer.exe "$(wslpath -w "$html")"); fi
else xdg-open "$html" >/dev/null 2>&1 &!
fi
