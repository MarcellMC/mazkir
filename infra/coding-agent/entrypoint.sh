#!/usr/bin/env bash
# infra/coding-agent/entrypoint.sh
# Manual smoke test for the coding-agent image — not invoked by application
# code (CodingTasksService.spawn_container runs `claude` directly), this is
# purely for verifying the image was built correctly after Step 3.
set -euo pipefail
echo "Checking claude CLI is installed..."
claude --version
echo "OK"
