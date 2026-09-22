#!/bin/sh
# PROTOTYPE: opens a VS Code window on the work root with this extension loaded (not installed).
exec code --new-window --extensionDevelopmentPath="$(cd "$(dirname "$0")" && pwd)" \
  "$HOME/Library/CloudStorage/OneDrive-IWGplc/work_sessions"
