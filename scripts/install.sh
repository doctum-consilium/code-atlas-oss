#!/usr/bin/env bash
# Purpose: Install (or update) code-atlas on a Linux machine, in one command.
# Usage:   bash scripts/install.sh [options]
#
#   --roots "~/code ~/work"   folders whose subfolders are git repositories (first install)
#   --no-gpu                  no NVIDIA card: the local models run on the CPU
#   --no-index                do not index now (the 03:30 timer will)
#   --no-models               do not download the chat model (~9 GB)
#   --no-desktop              do not build the Flutter desktop app
#   --check                   only check an existing installation
#   --uninstall               stop and remove the services (data, containers, models kept)
#
# Exit codes: 0 healthy installation; 1 missing prerequisite or failed final check.
#
# Re-runnable: every step first looks at what exists and only redoes what is missing. No secret
# is printed: the database password and the API token are generated into 0600 files. Everything
# that computes runs at low priority (nice), and indexing goes through the thermal guard.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_DIR="$HOME/.config/code-atlas"
CONFIG="$CONFIG_DIR/config.toml"
DATA="$HOME/.local/share/code-atlas"
UNITS="$HOME/.config/systemd/user"
DB_IMAGE="docker.io/paradedb/paradedb:v0.26.6-pg18"
OLLAMA_IMAGE="docker.io/ollama/ollama:latest"
export TMPDIR="$HOME/.cache/code-atlas/tmp"

GPU=1 INDEX=1 MODELS=1 DESKTOP=1 MODE=install ROOTS=""
while [ $# -gt 0 ]; do
  case "$1" in
    --roots) ROOTS="$2"; shift ;;
    --no-gpu) GPU=0 ;;
    --no-index) INDEX=0 ;;
    --no-models) MODELS=0 ;;
    --no-desktop) DESKTOP=0 ;;
    --check) MODE=check ;;
    --uninstall) MODE=uninstall ;;
    -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $1 (see --help)" >&2; exit 1 ;;
  esac
  shift
done

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
ok() { printf '    ✓ %s\n' "$*"; }
fail() { printf '    ✗ %s\n' "$*" >&2; }
gentle() { nice -n 10 "$@"; }
container_exists() { podman container exists "$1"; }
container_running() { [ "$(podman inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" = "true" ]; }

# ------------------------------------------------------------------ uninstall

if [ "$MODE" = uninstall ]; then
  step "Stopping and removing the services"
  systemctl --user disable --now code-atlas-api.service code-atlas-web.service \
    code-atlas-index.timer 2>/dev/null || true
  rm -f "$UNITS"/code-atlas-{api,web,index}.service "$UNITS"/code-atlas-index.timer
  systemctl --user daemon-reload
  for c in code-atlas-db code-atlas-ollama; do
    if container_running "$c"; then podman stop "$c" >/dev/null && ok "container $c stopped"; fi
  done
  ok "services removed"
  echo "    Kept: $DATA (database, models), $CONFIG_DIR (settings, password, token)."
  exit 0
fi

# ------------------------------------------------------------------ checks

HEALTHY=0
check() {
  local success="$1" failure="$2"
  shift 2
  if "$@"; then ok "$success"; else fail "$failure"; HEALTHY=1; fi
}
http_code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
equals() { [ "$1" = "$2" ]; }

verify() {
  step "Checks"
  HEALTHY=0
  check "API service active" "API service inactive" systemctl --user is-active --quiet code-atlas-api
  check "web service active" "web service inactive" systemctl --user is-active --quiet code-atlas-web
  check "nightly index timer active (03:30)" "index timer inactive" \
    systemctl --user is-active --quiet code-atlas-index.timer
  for _ in $(seq 60); do curl -fs http://127.0.0.1:8790/healthz >/dev/null && break; sleep 2; done
  check "API closed without a token (401)" "the API does not answer 401 without a token" \
    equals "$(http_code http://127.0.0.1:8790/v1/me)" 401
  check "foreign host refused (400)" "foreign host accepted" \
    equals "$(http_code -H 'Host: evil.example' http://127.0.0.1:8790/healthz)" 400
  check "web front served on 127.0.0.1:4173" "web front unreachable" \
    equals "$(http_code http://127.0.0.1:4173/)" 200
  local exposed
  exposed="$(ss -ltnH 2>/dev/null | awk '{print $4}' | grep -E ':(8790|4173|55432|11434)$' \
    | grep -vE '^(127\.0\.0\.1|\[::1\]):' || true)"
  check "nothing listens outside 127.0.0.1" "exposed outside loopback: $exposed" equals "$exposed" ""
  local chunks
  chunks="$(podman exec code-atlas-db psql -U atlas -d atlas -tAc 'SELECT count(*) FROM chunks' 2>/dev/null || echo 0)"
  if [ "${chunks:-0}" -gt 0 ]; then
    ok "index: $chunks chunks"
  else
    echo "    · empty index (run: cd backend && uv run atlas corpus && uv run atlas index)"
  fi
  return "$HEALTHY"
}

if [ "$MODE" = check ]; then verify; exit $?; fi

# ------------------------------------------------------------------ prerequisites

step "Prerequisites"
missing=0
for tool in git podman uv npm node curl ss systemctl python3; do
  if command -v "$tool" >/dev/null; then ok "$tool"; else fail "$tool missing"; missing=1; fi
done
if [ "$DESKTOP" = 1 ] && ! command -v flutter >/dev/null; then
  fail "flutter missing (or run again with --no-desktop)"; missing=1
fi
if [ "$GPU" = 1 ]; then
  if command -v nvidia-smi >/dev/null && grep -qs 'nvidia.com/gpu' /etc/cdi/*.yaml /var/run/cdi/*.yaml; then
    ok "NVIDIA GPU and CDI for podman"
  else
    fail "NVIDIA GPU or CDI missing (sudo nvidia-ctk cdi generate …), or run again with --no-gpu"
    missing=1
  fi
fi
[ "$missing" = 0 ] || { echo "Missing prerequisites: nothing was changed." >&2; exit 1; }
mkdir -p "$TMPDIR" "$CONFIG_DIR" "$DATA/db" "$DATA/ollama" "$UNITS"
chmod 700 "$CONFIG_DIR"

# ------------------------------------------------------------------ settings

step "Settings ($CONFIG)"
if [ ! -f "$CONFIG" ]; then
  cp "$ROOT/config/config.example.toml" "$CONFIG"
  if [ -n "$ROOTS" ]; then
    list="$(for r in $ROOTS; do printf '"%s", ' "$r"; done | sed 's/, $//')"
    sed -i "s|^roots = \[.*\]|roots = [$list]|" "$CONFIG"
  fi
  ok "created from config/config.example.toml — review [corpus] roots and owners"
else
  ok "kept as is"
fi
[ -f "$CONFIG_DIR/policy.toml" ] || cp "$ROOT/config/policy.example.toml" "$CONFIG_DIR/policy.toml"
model="$(sed -n 's/^local_default = "\(.*\)"/\1/p' "$CONFIG" | head -1)"

# ------------------------------------------------------------------ database and models

step "ParadeDB database (127.0.0.1:55432)"
if [ ! -s "$CONFIG_DIR/db-password" ]; then
  (umask 077; python3 -c "import secrets; print(secrets.token_urlsafe(32))" > "$CONFIG_DIR/db-password")
  ok "password generated in $CONFIG_DIR/db-password (0600, never shown)"
fi
if ! container_exists code-atlas-db; then
  podman run -d --name code-atlas-db --restart unless-stopped -p 127.0.0.1:55432:5432 \
    -e POSTGRES_USER=atlas -e POSTGRES_DB=atlas -e POSTGRES_PASSWORD_FILE=/run/secrets/pg \
    -v "$CONFIG_DIR/db-password:/run/secrets/pg:ro,Z" -v "$DATA/db:/var/lib/postgresql:Z" \
    "$DB_IMAGE" >/dev/null
  ok "container created"
else
  container_running code-atlas-db || podman start code-atlas-db >/dev/null
  ok "container already present"
fi
for _ in $(seq 60); do podman exec code-atlas-db pg_isready -U atlas -q 2>/dev/null && break; sleep 1; done
podman exec code-atlas-db pg_isready -U atlas -q && ok "database ready"

step "Ollama (127.0.0.1:11434)"
if ! container_exists code-atlas-ollama; then
  gpu_args=()
  [ "$GPU" = 1 ] && gpu_args=(--device nvidia.com/gpu=all)
  podman run -d --name code-atlas-ollama --restart unless-stopped "${gpu_args[@]}" \
    -e OLLAMA_KEEP_ALIVE=2m -e OLLAMA_NUM_PARALLEL=1 -e OLLAMA_MAX_LOADED_MODELS=1 \
    -p 127.0.0.1:11434:11434 -v "$DATA/ollama:/root/.ollama:Z" "$OLLAMA_IMAGE" >/dev/null
  ok "container created (model unloaded after 2 min, one at a time)"
else
  container_running code-atlas-ollama || podman start code-atlas-ollama >/dev/null
  ok "container already present"
fi
if [ "$MODELS" = 1 ] && [ -n "$model" ]; then
  if podman exec code-atlas-ollama ollama list 2>/dev/null | awk 'NR>1{print $1}' | grep -qx "$model"; then
    ok "$model already present"
  else
    echo "    downloading $model (several GB)…"
    podman exec code-atlas-ollama ollama pull "$model" >/dev/null && ok "$model downloaded"
  fi
fi

# ------------------------------------------------------------------ backend, web, desktop

step "Backend (Python 3.11)"
cd "$ROOT/backend"
extras=(--group dev)
[ "$GPU" = 1 ] && extras+=(--extra gpu)
[ -d .venv ] || uv venv -q -p 3.11
gentle uv sync -q "${extras[@]}" && ok "dependencies installed"
uv run python -c "from atlas import db; from atlas.config import Settings; s = Settings.load(); db.migrate(db.connect(s.database.dsn()), s.models.dimension)" \
  && ok "schema applied"
uv run atlas token | sed 's/^/    /'

if [ "$INDEX" = 1 ]; then
  step "Corpus and index (low priority, thermal guard)"
  gentle uv run atlas corpus --processes 4 >/dev/null && ok "corpus selected (report: $DATA/corpus-report.md)"
  echo "    indexing (about 25 min per 100k chunks with a GPU, then only changed files)…"
  nice -n 15 uv run atlas index && ok "index up to date"
fi

step "Web front"
cd "$ROOT/web"
gentle npm ci --silent --no-audit --no-fund && gentle npm run -s build >/dev/null && ok "build ready (web/dist)"

if [ "$DESKTOP" = 1 ]; then
  step "Desktop app (Flutter Linux)"
  cd "$ROOT/desktop"
  flutter pub get >/dev/null
  gentle flutter build linux --release < /dev/null >/dev/null && \
    ok "desktop/build/linux/x64/release/bundle/code_atlas"
fi

# ------------------------------------------------------------------ services

step "User services"
NODE="$(command -v node)"
declare -A values=(
  [@ROOT@]="$ROOT" [@UV@]="$(command -v uv)" [@PODMAN@]="$(command -v podman)"
  [@NODE@]="$NODE" [@NODE_DIR@]="$(dirname "$NODE")"
)
for template in "$ROOT"/deploy/systemd/*.{service,timer}; do
  target="$UNITS/$(basename "$template")"
  rm -f "$target"
  content="$(cat "$template")"
  for key in "${!values[@]}"; do content="${content//"$key"/${values[$key]}}"; done
  printf '%s\n' "$content" > "$target"
done
if grep -l '@[A-Z_]*@' "$UNITS"/code-atlas-* >/dev/null 2>&1; then fail "badly filled unit template"; exit 1; fi
systemctl --user daemon-reload
systemctl --user enable --quiet code-atlas-api.service code-atlas-web.service code-atlas-index.timer
systemctl --user restart code-atlas-api.service code-atlas-web.service
systemctl --user start code-atlas-index.timer
ok "api, web and nightly timer enabled"
if ! loginctl show-user "$USER" -p Linger 2>/dev/null | grep -q yes; then
  echo "    · Services start when you log in. To start them at boot: loginctl enable-linger $USER"
fi

verify || { echo "Installed, but a check failed (see above)." >&2; exit 1; }
cat <<END

code-atlas is installed.
  Web      : http://127.0.0.1:4173   (token: $CONFIG_DIR/api-token)
  Desktop  : $ROOT/desktop/build/linux/x64/release/bundle/code_atlas
  Terminal : cd $ROOT/backend && uv run atlas search "your query" --excerpts
  Check    : bash $ROOT/scripts/install.sh --check
END
