#!/usr/bin/env bash
# Deploy production vigild: idle check, fast-forward, restart, doctor, image
# rebuild when the range touched an image input, summary. Stops at the first
# failure. Exit 2 means "not idle; nothing changed".
#
# Usage: scripts/deploy.sh [--prod-dir DIR] [--data-dir DIR] [--no-rebuild] [--dry-run]
#   --prod-dir  the production checkout (default $VIGIL_PROD_DIR, then ~/vigil-prod)
#   --data-dir  vigild's data dir (default $VIGIL_DATA_DIR, then ~/vigil-data)
#   --no-rebuild  skip the dev-image rebuild even if images/ or prompts/ changed
#   --dry-run   print each step; change nothing
set -euo pipefail

PROD_DIR="${VIGIL_PROD_DIR:-$HOME/vigil-prod}"
DATA_DIR="${VIGIL_DATA_DIR:-$HOME/vigil-data}"
REBUILD=1
DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --prod-dir) PROD_DIR="${2:?--prod-dir needs a value}"; shift 2 ;;
    --data-dir) DATA_DIR="${2:?--data-dir needs a value}"; shift 2 ;;
    --no-rebuild) REBUILD=0; shift ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "deploy: unknown argument $1" >&2; exit 1 ;;
  esac
done

step() { echo "==> $*"; }
die() { echo "deploy: $*" >&2; exit 1; }
git_prod() { git -C "$PROD_DIR" "$@"; }

[ -d "$PROD_DIR/.git" ] || die "$PROD_DIR is not a git checkout"
export VIGIL_DATA_DIR="$DATA_DIR"

# 1. Idle check (read-only).
step "idle check"
DB="$DATA_DIR/vigil.db"
[ -f "$DB" ] || die "no database at $DB"
busy=""
jobs_busy="$(sqlite3 -readonly "$DB" \
  "SELECT id || ' (' || state || ')' FROM jobs WHERE state IN ('building','in_review')")"
[ -z "$jobs_busy" ] || busy+="jobs:"$'\n'"$jobs_busy"$'\n'
sess_busy="$(sqlite3 -readonly "$DB" \
  "SELECT id || ' (' || status || ')' FROM sessions WHERE status IN ('running','starting') AND ended_at IS NULL")"
[ -z "$sess_busy" ] || busy+="sessions:"$'\n'"$sess_busy"$'\n'
ctr_busy="$(docker ps --filter label=dev.vigil.job -q)"
[ -z "$ctr_busy" ] || busy+="containers:"$'\n'"$ctr_busy"$'\n'
if [ -n "$busy" ]; then
  echo "deploy: not idle; nothing changed. Running now:" >&2
  printf '%s' "$busy" >&2
  exit 2
fi
echo "idle"

# 2. Fast-forward.
old="$(git_prod rev-parse HEAD)"
if [ "$DRY" = 1 ]; then
  step "[dry-run] git -C $PROD_DIR fetch origin"
  step "[dry-run] git -C $PROD_DIR merge --ff-only origin/main"
  new="$(git_prod rev-parse origin/main)"
else
  step "fast-forward $PROD_DIR"
  [ -z "$(git_prod status --porcelain)" ] || die "$PROD_DIR is dirty; nothing changed"
  git_prod fetch origin
  git_prod merge --ff-only origin/main || die "not a fast-forward; nothing restarted"
  new="$(git_prod rev-parse HEAD)"
fi

# 3. Restart.
LABEL="gui/$(id -u)/dev.vigil.vigild"
if [ "$DRY" = 1 ]; then
  step "[dry-run] launchctl kickstart -k $LABEL"
  step "[dry-run] wait up to 60 s for 127.0.0.1:8787"
else
  step "restart vigild"
  launchctl kickstart -k "$LABEL"
  up=0
  for _ in $(seq 1 60); do
    if curl -s -o /dev/null --max-time 2 http://127.0.0.1:8787/api/health; then
      up=1
      break
    fi
    sleep 1
  done
  [ "$up" = 1 ] || die "vigild did not answer on 127.0.0.1:8787 within 60 s"
fi

# 4. Doctor. A fail line makes the exit non-zero; nothing is undone.
rc=0
if [ "$DRY" = 1 ]; then
  step "[dry-run] (cd $PROD_DIR && uv run python cli/vigil doctor)"
else
  step "vigil doctor"
  out="$(cd "$PROD_DIR" && uv run python cli/vigil doctor)" || rc=1
  printf '%s\n' "$out"
  if printf '%s\n' "$out" | grep -qE '^fail'; then rc=1; fi
fi

# 5. Rebuild dev images when the range touched an image input.
rebuilt=""
touched="$(git_prod diff --name-only "$old" "$new" | grep -E '^(images/|prompts/|pyproject\.toml$|uv\.lock$)' || true)"
if [ -n "$touched" ] && [ "$REBUILD" = 1 ]; then
  repos="$(grep -E '^  [A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+:' "$PROD_DIR/configs/repos.yaml" | tr -d ' :')"
  for repo in $repos; do
    if [ "$DRY" = 1 ]; then
      step "[dry-run] uv run python cli/vigil dev-image --repo $repo --rebuild"
    else
      step "rebuild $repo"
      (cd "$PROD_DIR" && uv run python cli/vigil dev-image --repo "$repo" --rebuild) || rc=1
    fi
    rebuilt+="$repo "
  done
elif [ -n "$touched" ]; then
  echo "image inputs changed; --no-rebuild set, rebuild by hand"
fi

# 6. Summary.
if [ "$DRY" = 1 ]; then
  step "[dry-run] would deploy production ${old:0:7} → ${new:0:7}"
else
  echo
  echo "production ${old:0:7} → ${new:0:7}"
  git_prod log --oneline "$old..$new"
  echo "rebuilt: ${rebuilt:-none}"
fi
exit "$rc"
