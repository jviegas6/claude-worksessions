#!/bin/zsh
PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
# Render a Markdown file to styled HTML and open it in the default browser (for copy → email)
src="$1"; out="${TMPDIR:-/tmp}/md-email"; mkdir -p "$out"
html="$out/${${src:t}:r}.html"
pandoc "$src" -f gfm -t html5 -s --metadata title="${${src:t}:r}" \
  -H "$HOME/.config/yazi/md-email.css" -o "$html" && open "$html"
