#!/usr/bin/env bash
# Purpose: Replay the GitHub CI checks locally.
# Usage:   bash scripts/ci_local.sh [--e2e]
#          --e2e adds the browser journey (API already running in token mode, see README).
# Exit codes: 0 when every check is green; 1 otherwise. A missing tool is a failure, never a
#             silent skip. Everything runs at low priority (nice) to spare laptops.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export TMPDIR="${TMPDIR_CI:-$HOME/.cache/code-atlas/tmp}"
mkdir -p "$TMPDIR"
gentle() { nice -n 10 "$@"; }

for tool in uv npm flutter gitleaks shellcheck; do
  command -v "$tool" >/dev/null || { echo "Missing tool: $tool" >&2; exit 1; }
done
[ -n "${CODE_ATLAS_TEST_DSN:-}" ] || { echo "No test database (CODE_ATLAS_TEST_DSN)" >&2; exit 1; }
export CI=1   # database tests fail instead of being skipped

echo "==> Leak guard (tree and history)"
bash "$root/scripts/leak-guard.sh"
bash "$root/scripts/leak-guard.sh" --history

echo "==> Backend"
cd "$root/backend"
uv sync -q --group dev --inexact   # keeps a local GPU install (torch) in place
uv run ruff check .
uv run ruff format --check .
uv run mypy
gentle uv run pytest -q --cov=atlas --cov-report=xml --cov-fail-under=85
uv run bandit -q -r atlas -s B101,B603,B607,B404
uv export -q --no-dev --frozen --extra gpu --no-emit-project -o "$TMPDIR/requirements.txt"
uv run pip-audit -r "$TMPDIR/requirements.txt" --strict --disable-pip

echo "==> Contract"
uv run atlas openapi --output ../contract/openapi.yaml
git -C "$root" diff --exit-code contract

echo "==> Web"
cd "$root/web"
npm ci --silent
npm run -s contract && git -C "$root" diff --exit-code web/src/api/schema.d.ts
npm run -s lint
npm run -s typecheck
gentle npm test --silent
gentle npm run -s build
npm audit --omit=dev --audit-level=high

echo "==> Flutter desktop"
cd "$root/desktop"
flutter pub get >/dev/null
flutter analyze --fatal-infos
gentle flutter test --coverage < /dev/null

echo "==> Shell scripts and secrets"
shellcheck -x "$root"/scripts/*.sh "$root"/.githooks/*
gitleaks git --redact --no-banner "$root"

if [ "${1:-}" = "--e2e" ]; then
  echo "==> End to end"
  cd "$root/web" && gentle npx playwright test
fi

echo "Local CI green."
