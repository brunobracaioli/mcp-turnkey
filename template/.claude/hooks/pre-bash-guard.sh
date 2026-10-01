#!/usr/bin/env bash
# pre-bash-guard.sh
# Blocks destructive or unsafe commands before they run.
# Contract with Claude Code:
#   - exit 0  → allow
#   - exit 2  → block and send stderr back to Claude
set -euo pipefail

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""')

# Forbidden patterns. Each line is a regex (POSIX ERE — used with grep -E).
# Careful when editing: loose patterns cause false positives; anchor the command's
# target (space or end of line) whenever possible.
DANGEROUS_PATTERNS=(
  'rm -rf +/([[:space:]]|$)'        # a literal `rm -rf /`, not `rm -rf /tmp/...`
  'rm -rf +\*([[:space:]]|$)'
  'rm -rf +~([[:space:]]|$)'
  '> +/dev/sd[a-z]'
  'dd .*of=/dev/sd[a-z]'
  'mkfs\.'
  ':\(\)\{ *:\|: *& *\};:'           # fork bomb
  'curl [^|]* \| *(sh|bash)'
  'wget [^|]* \| *(sh|bash)'
  'chmod -R 777 +/([[:space:]]|$)'
  '\bDROP DATABASE\b'
  '\bDROP TABLE\b'
  '\bTRUNCATE TABLE\b'
  'git push +(--force|-f) +origin +(main|master|production)\b'
)

for pattern in "${DANGEROUS_PATTERNS[@]}"; do
  if echo "$COMMAND" | grep -qE "$pattern"; then
    echo "🚫 Command blocked by pre-bash-guard: pattern '$pattern' matched." >&2
    echo "If this is intentional, run it yourself in a terminal." >&2
    exit 2
  fi
done

# Blocks removing sensitive paths. Anchors `rm` at the start of a command (after
# start, ;, &, |) and only inspects arguments up to the next separator, avoiding a
# false positive when the sensitive name appears in another command on the same line.
if echo "$COMMAND" | grep -qE '(^|[;&|]) *rm [^;&|]*(\.env(\.|$|[[:space:]/])|/secrets/|/credentials(\.|/))'; then
  echo "⚠️  Attempt to remove a sensitive file. Confirm this is intentional." >&2
  exit 2
fi

exit 0
