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
if [ "$failures" -ne 0 ]; then
  echo "SMOKE TEST FAILED: $failures check(s) failed"
  exit 1
fi
echo "SMOKE TEST PASSED"
