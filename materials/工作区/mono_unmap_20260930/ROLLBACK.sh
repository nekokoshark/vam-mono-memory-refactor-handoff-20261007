#!/usr/bin/env bash
set -euo pipefail
PATH="/usr/bin:/bin:${PATH:-}"
export PATH

root=$(cd -- "$(dirname -- "$0")" && pwd -P)
target=$(realpath -m -- "${1:-$root}")
case "$target" in
  "$root"|"$root"/*) ;;
  *) printf '%s\n' 'ROLLBACK_TARGET_OUTSIDE_TOOL_DIRECTORY'; exit 2 ;;
esac

mkdir -p -- "$target"
cp -- "$root/BASELINE.py" "$target/MODIFIED_FILE.py"
expected=$(sha256sum -- "$root/BASELINE.py" | cut -d ' ' -f 1)
restored=$(sha256sum -- "$target/MODIFIED_FILE.py" | cut -d ' ' -f 1)
test "$expected" = "$restored"
printf 'ROLLBACK_PASS restoredHash=%s target=%s runtimeWrites=0\n' "$restored" "$target"
