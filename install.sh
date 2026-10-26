#!/usr/bin/env bash
# PRISM Cross-Harness Installer
# Links PRISM into active global skill directories and builds the initial Shadow Index.
set -euo pipefail

PRISM_DIR="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HOME/.agents/vault"
if [ "$PRISM_DIR" != "$HOME/.agents/prism" ]; then
  ln -sfn "$PRISM_DIR" "$HOME/.agents/prism"
fi

linked=0
for dir in "$HOME/.gemini/config/skills" "$HOME/.claude/skills" "$HOME/.codex/skills"; do
  if [ -d "$(dirname "$dir")" ]; then
    mkdir -p "$dir"
    ln -sfn "$PRISM_DIR" "$dir/prism"
    echo "🔗 Linked PRISM -> $dir/prism"
    linked=$((linked + 1))
  fi
done

if [ "$linked" -eq 0 ]; then
  mkdir -p "$HOME/.agents/skills"
  ln -sfn "$PRISM_DIR" "$HOME/.agents/skills/prism"
  echo "🔗 Linked PRISM -> $HOME/.agents/skills/prism"
fi

python3 "$PRISM_DIR/scripts/prism.py" index
echo "✅ PRISM installed and indexed! Run: python3 $PRISM_DIR/scripts/prism.py audit"
