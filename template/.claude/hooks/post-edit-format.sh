#!/usr/bin/env bash
# post-edit-format.sh
# Formats and lints a Python file right after Write/Edit (silent when clean).
# Gotcha: `ruff check --fix` removes imports that are not used YET — add an import
# in the same edit as its first use, or it disappears.
set -uo pipefail

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // ""')

[ -z "$FILE_PATH" ] && exit 0
[ ! -f "$FILE_PATH" ] && exit 0

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}"

errors=""
case "${FILE_PATH##*.}" in
  py)
    if command -v ruff >/dev/null 2>&1; then
      ruff format "$FILE_PATH" 2>/dev/null || true
      ruff check --fix "$FILE_PATH" 2>/dev/null || errors+="ruff failed on $FILE_PATH\n"
    fi
    ;;
  json)
    if command -v jq >/dev/null 2>&1; then
      jq empty "$FILE_PATH" 2>/dev/null || errors+="invalid JSON in $FILE_PATH\n"
    fi
    ;;
esac

if [ -n "$errors" ]; then
  echo -e "$errors" >&2
  exit 2
fi
exit 0
