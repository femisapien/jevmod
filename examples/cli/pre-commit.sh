#!/usr/bin/env bash
# Git pre-commit hook: refuse the commit when a staged .md or .txt file contains a line that triggers moderation.
# Install: cp examples/cli/pre-commit.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
set -uo pipefail
SCREEN="$(git rev-parse --show-toplevel)/examples/cli/screen_file.sh"

failed=0
while IFS= read -r file; do
  [ -n "$file" ] || continue
  if ! bash "$SCREEN" "$file"; then
    echo "moderation hit in $file" >&2
    failed=1
  fi
done < <(git diff --cached --name-only --diff-filter=ACM -- '*.md' '*.txt')
exit $failed
