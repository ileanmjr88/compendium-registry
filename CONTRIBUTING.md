# Contributing

The registry is data first — most contributions add a new tool, extend the
version range of an existing tool, or fix a checksum. The Python scripts under
`scripts/` exist to keep the JSON current; you'll spend most of your time
running them and reviewing their output.

## Local development

```sh
# Refresh manifests from upstream
GITHUB_TOKEN=$(gh auth token) python3 scripts/build_manifest_split.py

# Resolve any sha256:FILL_IN entries
GITHUB_TOKEN=$(gh auth token) python3 scripts/fetch_checksums.py

# Confirm shape before opening a PR
python3 scripts/validate_manifest.py
```

`GITHUB_TOKEN` is optional but recommended — the GitHub API limits
unauthenticated callers to 60 requests/hour, and a full refresh easily exceeds
that.

## Adding a tool

For tools that publish standard GitHub release assets:

1. Add an entry to `scripts/build_manifest_split.py` — either in the `github_tools`
   list (for `tools/`) or in the languages block (for `languages/`). For xPack
   tools the helper is `fetch_xpack_tool(repo, tool_name)`. For other GitHub
   projects, `fetch_github_tool(owner, repo, tool_name, version_regex, file_patterns)`.
2. Run `scripts/build_manifest_split.py` followed by `scripts/fetch_checksums.py`.
3. Run `scripts/validate_manifest.py`.
4. Commit the new `languages/<name>.json` or `tools/<name>.json` plus the
   updated `index.json`. The scheduled workflow will pick the tool up on its
   next run from then on.

For tools that need assembly (e.g. vcpkg, where the binary lives in one repo
and the scripts in another), add a packager in `scripts/package_tools.py` following
the `package_vcpkg()` pattern, and add the assembled tarball URLs by hand in
the per-tool JSON (the `tools/vcpkg.json` entries are good references).

## Automated updates

Two workflows in `.github/workflows/` keep the registry fresh and honest:

### `update-registry.yml`

Runs Mondays, Wednesdays, and Fridays at 06:17 UTC, and on demand via the
Actions tab.

1. `scripts/build_manifest_split.py` — for each tool, asks upstream for the latest tag.
   If we already have it (per `index.json`), the tool is skipped. Otherwise it
   pulls the recent releases page and merges any new versions into the per-tool
   file. New entries land with `"checksum": "sha256:FILL_IN"` if upstream
   doesn't expose a checksum directly on the asset.
2. `scripts/fetch_checksums.py` — scans every per-tool file for `FILL_IN`, resolves
   via:
   1. companion `.sha` / `.sha256` / `.sha256sum` file
   2. aggregate `SHA256SUMS` / `checksums.txt` in the release
   3. project-specific files (golangci-lint, pnpm)
   4. streaming the artifact and hashing it locally
3. `scripts/validate_manifest.py` — schema + integrity check.
4. If any tracked file changed, open a PR (branch `automation/update-registry`)
   labeled `automation` / `registry-update`. The validate workflow then runs on
   the PR; the reviewer just has to confirm the diff looks sane before merging.

Trigger manually with `gh workflow run update-registry.yml -f reason="..."` or
from the Actions tab. The `concurrency` group prevents a manual run from
clashing with the scheduled one.

### `validate-manifest.yml`

Runs on every PR touching `index.json`, `languages/`, `tools/`, or the
validator itself, and on pushes to `main` as a smoke test. Cheap (~30s) — no
downloads, just JSON shape, sha256 format, and index-vs-per-tool consistency.
