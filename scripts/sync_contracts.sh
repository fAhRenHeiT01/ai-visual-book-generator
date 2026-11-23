#!/usr/bin/env bash
# Regenerate both artifacts from the application factory. --check never writes them.
set -euo pipefail

cd "$(dirname "$0")/.."
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--check" ) ]]; then
  echo "Usage: $0 [--check]" >&2
  exit 2
fi

temporary_dir=$(mktemp -d)
cleanup() {
  rm -f "$temporary_dir/openapi.json" "$temporary_dir/generated.ts"
  rmdir "$temporary_dir"
}
trap cleanup EXIT
export PYTHONPATH="$(pwd)/apps/api/src${PYTHONPATH:+:$PYTHONPATH}"
"${PYTHON:-python}" -m bookgen.main --export-openapi "$temporary_dir/openapi.json"
# Resolve the locally installed, lockfile-pinned CLI; never fetch a tool during checks.
node apps/web/node_modules/openapi-typescript/bin/cli.js "$temporary_dir/openapi.json" --output "$temporary_dir/generated.ts"

if [[ "${1:-}" == "--check" ]]; then
  drift=0
  for pair in 'apps/api/openapi.json:openapi.json' 'apps/web/src/types/generated.ts:generated.ts'; do
    committed=${pair%%:*}
    generated=${pair#*:}
    if ! cmp -s "$committed" "$temporary_dir/$generated"; then
      echo "Contract drift: $committed (run make sync-contracts)" >&2
      drift=1
    fi
  done
  exit "$drift"
fi

mkdir -p apps/web/src/types
cp "$temporary_dir/openapi.json" apps/api/openapi.json
cp "$temporary_dir/generated.ts" apps/web/src/types/generated.ts
