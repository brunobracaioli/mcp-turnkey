#!/usr/bin/env bash
# pre-commit-secrets.sh
# Runs only on `git commit` / `git push` commands.
# Blocks when a secret pattern shows up in the staged files.
set -uo pipefail

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""')

# Only for git commit/push (early return for anything else)
if ! echo "$COMMAND" | grep -qE '^git (commit|push)'; then
  exit 0
fi

# Secret patterns (regex). Keep them conservative to avoid false positives.
SECRET_PATTERNS=(
  '-----BEGIN (RSA|OPENSSH|EC|DSA|PGP) PRIVATE KEY-----'
  'AKIA[0-9A-Z]{16}'                              # AWS Access Key
  'aws_secret_access_key\s*=\s*[A-Za-z0-9/+=]{40}' # AWS Secret
  'ghp_[A-Za-z0-9]{36}'                            # GitHub PAT
  'gho_[A-Za-z0-9]{36}'                            # GitHub OAuth
  'sk-ant-api[0-9]{2}-[A-Za-z0-9_-]{90,}'          # Anthropic API key
  'sk-[A-Za-z0-9]{48}'                             # OpenAI key (legado)
  'xox[baprs]-[A-Za-z0-9-]{10,}'                   # Slack tokens
  'EAA[A-Za-z0-9]{50,}'                            # Meta/FB long-lived tokens
)

# Staged files
STAGED=$(git diff --cached --name-only --diff-filter=ACM 2>/dev/null || true)
[ -z "$STAGED" ] && exit 0

found=""
while IFS= read -r file; do
  [ ! -f "$file" ] && continue
  # Skip binaries
  if file "$file" 2>/dev/null | grep -q 'binary'; then continue; fi

  for pattern in "${SECRET_PATTERNS[@]}"; do
    if grep -qE "$pattern" "$file" 2>/dev/null; then
      found+="  • $file (pattern: $pattern)\n"
      break
    fi
  done
done <<< "$STAGED"

if [ -n "$found" ]; then
  echo "🚨 Possible secrets found in the staged files:" >&2
  echo -e "$found" >&2
  echo "Remove them or move them to .env before committing." >&2
  echo "If it is a false positive, commit manually outside Claude." >&2
  exit 2
fi

exit 0
