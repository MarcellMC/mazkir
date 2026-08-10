#!/usr/bin/env bash
# infra/coding-agent/smoke-test.sh
#
# Opt-in smoke test: boots the real devcontainer image and asserts the
# things unit tests cannot. Requires Docker and network. Not part of
# `turbo test` -- run before merging any container change.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${IMAGE:-mazkir-coding-agent:latest}"
failures=0

check() {
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then
    echo "  PASS  $name"
  else
    echo "  FAIL  $name"
    failures=$((failures + 1))
  fi
}

echo "== image capabilities =="
check "python3 present"  docker run --rm "$IMAGE" python3 --version
check "uv present"       docker run --rm "$IMAGE" uv --version
check "node present"     docker run --rm "$IMAGE" node --version
check "git present"      docker run --rm "$IMAGE" git --version
check "gh present"       docker run --rm "$IMAGE" gh --version
check "claude present"   docker run --rm "$IMAGE" claude --version

echo
echo "== session provisioning =="
SMOKE_ROOT="$(mktemp -d)"
SMOKE_NAME="smoke-$$"
cleanup_smoke() {
  "$SCRIPT_DIR/session.sh" clean "$SMOKE_NAME" --root="$SMOKE_ROOT" --force >/dev/null 2>&1 || true
  rm -rf "$SMOKE_ROOT"
}
trap cleanup_smoke EXIT

"$SCRIPT_DIR/session.sh" provision "$SMOKE_NAME" --root="$SMOKE_ROOT" >/dev/null

check "clone has a GitHub origin" bash -c \
  "git -C '$SMOKE_ROOT/$SMOKE_NAME' remote get-url origin | grep -q github.com"
check "session .env has container paths" bash -c \
  "grep -q '^VAULT_PATH=/workspace/memory\$' '$SMOKE_ROOT/$SMOKE_NAME/apps/vault-server/.env'"

echo
echo "== container boots against a real session =="
# Real files, not process substitution: launch reads the brief and writes
# it into the session, and a fifo cannot be consumed twice.
BOOT_PROMPT="$SMOKE_ROOT/boot-prompt.md"
echo 'Reply with exactly: BOOT OK' > "$BOOT_PROMPT"
CTX_PROMPT="$SMOKE_ROOT/ctx-prompt.md"
echo 'Without reading any files, what port does vault-server run on?' > "$CTX_PROMPT"

check "agent answers in the session" bash -c \
  "'$SCRIPT_DIR/session.sh' launch '$SMOKE_NAME' --root='$SMOKE_ROOT' --mode=autonomous \
     --prompt-file='$BOOT_PROMPT' 2>&1 | grep -q 'BOOT OK'"
check "CLAUDE.md is autoloaded" bash -c \
  "'$SCRIPT_DIR/session.sh' launch '$SMOKE_NAME' --root='$SMOKE_ROOT' --mode=autonomous \
     --prompt-file='$CTX_PROMPT' 2>&1 | grep -q '8000'"

echo
echo "== detached launch returns immediately =="
# The server calls session.sh and must get control back. `docker compose
# run` is foreground by default, and a real autonomous launch blocked the
# request thread for 130s before this check existed.
DETACH_NAME="smokedetach-$$"
"$SCRIPT_DIR/session.sh" provision "$DETACH_NAME" --root="$SMOKE_ROOT" >/dev/null
detach_start=$(date +%s)
"$SCRIPT_DIR/session.sh" launch "$DETACH_NAME" --root="$SMOKE_ROOT" \
  --mode=autonomous --prompt-file="$BOOT_PROMPT" --detach >/dev/null 2>&1
detach_elapsed=$(( $(date +%s) - detach_start ))

check "launch returned in under 20s" test "$detach_elapsed" -lt 20
check "container is named predictably" \
  docker inspect "mazkir-coding-$DETACH_NAME"
docker rm -f "mazkir-coding-$DETACH_NAME" >/dev/null 2>&1 || true
"$SCRIPT_DIR/session.sh" clean "$DETACH_NAME" --root="$SMOKE_ROOT" --force >/dev/null 2>&1 || true

echo
if [ "$failures" -ne 0 ]; then
  echo "SMOKE TEST FAILED: $failures check(s) failed"
  exit 1
fi
echo "SMOKE TEST PASSED"
