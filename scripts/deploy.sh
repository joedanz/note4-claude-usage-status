#!/usr/bin/env bash
# Push note4-claude to another Mac over SSH (Remote Login) and (re)install its LaunchAgent.
# usage: scripts/deploy.sh [--dry-run] [--no-install] [--python PATH] USER@HOST
# --no-install syncs the code and builds the venv only (do the first sign-in, then run without it).
set -euo pipefail

REMOTE_DIR="note4-claude"
REMOTE_PYTHON="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
DRY=0
INSTALL=1

usage() { echo "usage: $0 [--dry-run] [--no-install] [--python PATH] USER@HOST" >&2; exit 2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    --no-install) INSTALL=0; shift ;;
    --python) [ $# -ge 2 ] || usage; REMOTE_PYTHON="$2"; shift 2 ;;
    -h|--help) usage ;;
    -*) usage ;;
    *) break ;;
  esac
done
[ $# -eq 1 ] || usage
TARGET="$1"

run() {
  if [ "$DRY" -eq 1 ]; then echo "+ $*"; else "$@"; fi
}

cd "$(dirname "$0")/.."

# Never ship the firmware tree (it holds the Wi-Fi password in secrets.local.h), the venv, VCS or scratch.
run rsync -az --delete \
  --exclude .git --exclude .venv --exclude firmware --exclude secrets.local.h \
  --exclude .worktrees --exclude .superpowers --exclude preview --exclude tasks \
  --exclude __pycache__ --exclude .pytest_cache --exclude '*.egg-info' \
  ./ "$TARGET:$REMOTE_DIR/"

# Create the venv with an explicit interpreter (the system python3 over SSH is too old), then install.
VENV="cd $REMOTE_DIR && { [ -x .venv/bin/python ] || $REMOTE_PYTHON -m venv .venv; } && .venv/bin/pip install -q -e ."
if [ "$INSTALL" -eq 1 ]; then
  # `setup` creates the device key; only when there is no config yet, so an existing config is never overwritten.
  run ssh "$TARGET" "$VENV && { [ -f ~/.config/note4-claude/config.toml ] || .venv/bin/note4-claude setup; } && .venv/bin/note4-claude install && .venv/bin/note4-claude doctor"
else
  run ssh "$TARGET" "$VENV"
fi

if [ "$DRY" -eq 1 ]; then echo "(dry run: nothing was copied or changed)"; fi
