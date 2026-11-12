#!/usr/bin/env bash
# Purpose: Refuse to commit or push anything that contains one of YOUR private terms.
# Usage:   bash scripts/leak-guard.sh [--staged | --history]
#            (no option)  every tracked file of the working tree
#            --staged     only what is about to be committed (pre-commit hook)
#            --history    every commit message and every version of every file (pre-push hook)
#
# The list of private terms is NEVER stored in the repository: one term per line in
#   ${CODE_ATLAS_PRIVATE_TERMS:-~/.config/code-atlas-oss/private-terms.txt}
# (names, e-mail addresses, domains, internal project names, account numbers…). Lines starting
# with # are comments. Matching is case-insensitive and on whole words.
#
# Exit codes: 0 nothing found (or no list: warning), 1 a private term was found. The matching
# term itself is never printed — only the file and line — so the guard cannot leak it either.
set -euo pipefail

list="${CODE_ATLAS_PRIVATE_TERMS:-$HOME/.config/code-atlas-oss/private-terms.txt}"
mode="${1:-tree}"
cd "$(git rev-parse --show-toplevel)"

if [ ! -s "$list" ]; then
  echo "leak-guard: no private-terms list at $list (nothing checked)." >&2
  exit 0
fi

patterns="$(mktemp)"
trap 'rm -f "$patterns"' EXIT
grep -vE '^\s*(#|$)' "$list" > "$patterns" || true
[ -s "$patterns" ] || exit 0

found=0
report() { echo "leak-guard: private term found in $1" >&2; found=1; }

case "$mode" in
  --staged)
    while IFS= read -r -d '' file; do
      if git show ":$file" 2>/dev/null | grep -qiwFf "$patterns"; then report "$file (staged)"; fi
    done < <(git diff --cached --name-only -z --diff-filter=ACMR)
    ;;
  --history)
    if git log --all --format='%B' | grep -qiwFf "$patterns"; then report "a commit message"; fi
    while read -r commit; do
      if git grep -qiwFf "$patterns" "$commit" -- . 2>/dev/null; then
        report "commit $commit"
      fi
    done < <(git rev-list --all)
    ;;
  tree|*)
    while IFS= read -r line; do report "$line"; done < <(
      git grep --untracked -niwFf "$patterns" -- . 2>/dev/null | cut -d: -f1,2 || true)
    ;;
esac

if [ "$found" = 1 ]; then
  echo "leak-guard: refused. Remove the private term(s) above (the term is not shown on purpose)." >&2
  exit 1
fi
echo "leak-guard: no private term found ($mode)."
