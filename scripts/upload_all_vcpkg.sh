#!/usr/bin/env bash
# Create one GitHub release per vcpkg version and upload its tarballs + checksums.
# Idempotent: skips a version whose release already exists.
set -uo pipefail

cd "$(dirname "$0")/.."

LATEST_VERSION="2026-04-08"

ok=0
skip=0
fail=0
failed_versions=()

for cs in packages/vcpkg-*-checksums.txt; do
  v=$(basename "$cs" | sed 's|^vcpkg-||;s|-checksums.txt$||')
  tag="vcpkg-$v"
  echo "==== $tag ===="

  if gh release view "$tag" >/dev/null 2>&1; then
    echo "  release already exists, skipping"
    skip=$((skip+1))
    continue
  fi

  notes="Compendium-packaged vcpkg $v.

Each tarball contains:
- The vcpkg repository at this release tag (no .git history)
- \`bin/vcpkg\` — pre-built binary for the platform
- \`.vcpkg-root\` marker
- No-op bootstrap scripts (the binary is provided)

Older releases ship without \`linux-arm64\` because the upstream \`vcpkg-tool\`
project did not publish a glibc-arm64 binary at the time."

  cmd=(gh release create "$tag"
    --title "vcpkg $v"
    --notes "$notes")
  if [ "$v" = "$LATEST_VERSION" ]; then
    cmd+=(--latest)
  fi
  for f in packages/vcpkg-$v-*.tar.gz; do
    cmd+=("$f")
  done
  cmd+=("$cs")

  if "${cmd[@]}"; then
    echo "  ✓"
    ok=$((ok+1))
  else
    echo "  ✗"
    fail=$((fail+1))
    failed_versions+=("$v")
  fi
done

echo
echo "==== summary ===="
echo "created: $ok"
echo "skipped: $skip"
echo "failed:  $fail"
if [ "$fail" -gt 0 ]; then
  echo "failed versions: ${failed_versions[*]}"
fi
