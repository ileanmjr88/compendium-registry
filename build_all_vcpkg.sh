#!/usr/bin/env bash
# One-shot driver to package every version listed in tools/vcpkg.json.
# Skips versions whose linux-amd64 tarball already exists in packages/.
set -uo pipefail

cd "$(dirname "$0")"
mkdir -p logs packages

versions=$(python3 -c "import json; print(' '.join(sorted(json.load(open('tools/vcpkg.json')).keys(), reverse=True)))")

ok=0
skip=0
fail=0
failed_versions=()

for v in $versions; do
  if [ -f "packages/vcpkg-$v-linux-amd64.tar.gz" ]; then
    echo "[$v] already built, skipping"
    skip=$((skip+1))
    continue
  fi
  echo "[$v] building..."
  if python3 package_tools.py vcpkg "$v" >"logs/vcpkg-$v.log" 2>&1; then
    echo "[$v] ✓"
    ok=$((ok+1))
  else
    echo "[$v] ✗ (see logs/vcpkg-$v.log)"
    fail=$((fail+1))
    failed_versions+=("$v")
  fi
done

echo
echo "==== summary ===="
echo "built:   $ok"
echo "skipped: $skip"
echo "failed:  $fail"
if [ "$fail" -gt 0 ]; then
  echo "failed versions: ${failed_versions[*]}"
fi
