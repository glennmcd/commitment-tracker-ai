#!/usr/bin/env bash
# Runs every check a change must pass. Prints one line per check, and the full
# output only for a check that fails. Runs all checks even after a failure, so
# one run shows every problem. Exits 1 if any check failed.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
logs="$(mktemp -d "${TMPDIR:-/tmp}/check.XXXXXX")"
trap 'rm -rf "$logs"' EXIT

failed=0
count=0

# run NAME COMMAND... : quiet on success, shows the captured output on failure.
run() {
  local name="$1"
  shift
  count=$((count + 1))
  local log="$logs/$count.log"
  if "$@" >"$log" 2>&1; then
    echo "ok    $name"
  else
    echo "FAIL  $name"
    cat "$log"
    failed=1
  fi
}

in_backend() { (cd "$root/backend" && "$@"); }
in_root() { (cd "$root" && "$@"); }

run "ruff check" in_backend uv run ruff check .
run "ruff format" in_backend uv run ruff format --check .
run "mypy" in_backend uv run mypy
run "pytest" in_backend uv run pytest -q
run "eval-gate" in_backend uv run eval-gate
run "bun lint" in_root bun run lint
run "bun typecheck" in_root bun run typecheck
run "bun test" in_root bun run test

exit "$failed"
