#!/usr/bin/env python3
"""Validate the split manifest structure.

Checks, for every per-tool file referenced by index.json:
  - the file exists and parses as JSON
  - every entry is a {version: {os: {arch: artifact}}} map
  - every artifact has url, checksum, size, strip
  - checksum is "sha256:" + 64 hex chars (no FILL_IN, no empty)
  - tools in REQUIRED_DEPENDS declare that dependency on every version
  - index.json's `versions` count matches the per-tool file
  - index.json's `latest` exists in the per-tool file

Exits 0 if valid, 1 otherwise. Used by .github/workflows/validate-manifest.yml
and runnable locally before opening a PR.
"""

import json
import re
import sys
from pathlib import Path

CHECKSUM_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
REQUIRED_ARTIFACT_KEYS = {"url", "checksum", "size", "strip"}

# Tools whose every version must declare a runtime dependency. Clang ships an
# lldb linked against a specific libpython, so an entry without depends.python
# installs a broken lldb — see LLVM_PYTHON_DEPENDS in build_manifest_split.py.
REQUIRED_DEPENDS = {"clang": "python"}


def validate_artifact(artifact: dict, path: str) -> list[str]:
    errors = []
    if not isinstance(artifact, dict):
        return [f"{path}: not an object"]
    missing = REQUIRED_ARTIFACT_KEYS - artifact.keys()
    if missing:
        errors.append(f"{path}: missing keys {sorted(missing)}")
    checksum = artifact.get("checksum", "")
    if checksum == "sha256:FILL_IN":
        errors.append(f"{path}: checksum is FILL_IN (run scripts/fetch_checksums.py)")
    elif not CHECKSUM_RE.match(checksum):
        errors.append(f"{path}: checksum {checksum!r} is not sha256:<64-hex>")
    url = artifact.get("url", "")
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        errors.append(f"{path}: url {url!r} is not http(s)")
    if not isinstance(artifact.get("size", 0), int):
        errors.append(f"{path}: size is not an integer")
    if not isinstance(artifact.get("strip", 0), int):
        errors.append(f"{path}: strip is not an integer")
    link = artifact.get("link_bin_from")
    if link is not None:
        if not isinstance(link, str) or not link:
            errors.append(f"{path}: link_bin_from must be a non-empty string")
        elif link.startswith("/") or ".." in link.split("/"):
            errors.append(f"{path}: link_bin_from must be a relative path without '..' segments")
    return errors


def validate_tool_file(file_path: Path) -> tuple[list[str], dict]:
    """Return (errors, version_map)."""
    if not file_path.exists():
        return [f"{file_path}: file missing"], {}
    try:
        data = json.loads(file_path.read_text())
    except json.JSONDecodeError as e:
        return [f"{file_path}: invalid JSON ({e})"], {}
    if not isinstance(data, dict):
        return [f"{file_path}: top level is not an object"], {}

    errors = []
    required_dep = REQUIRED_DEPENDS.get(file_path.stem)
    for version, platforms in data.items():
        if not isinstance(platforms, dict):
            errors.append(f"{file_path}:{version}: platforms not an object")
            continue
        if required_dep:
            depends = platforms.get("depends")
            value = depends.get(required_dep) if isinstance(depends, dict) else None
            if value is None:
                errors.append(
                    f"{file_path}:{version}: missing depends.{required_dep}"
                )
            elif value == "FILL_IN":
                errors.append(
                    f"{file_path}:{version}: depends.{required_dep} is FILL_IN "
                    f"(add the major to LLVM_PYTHON_DEPENDS in build_manifest_split.py)"
                )
        for key, value in platforms.items():
            if key == "depends":
                if not isinstance(value, dict):
                    errors.append(f"{file_path}:{version}.depends: not an object")
                continue
            os_name = key
            arches = value
            if not isinstance(arches, dict):
                errors.append(f"{file_path}:{version}.{os_name}: not an object")
                continue
            for arch, artifact in arches.items():
                errors.extend(
                    validate_artifact(artifact, f"{file_path}:{version}.{os_name}.{arch}")
                )
    return errors, data


def main() -> int:
    index_path = Path("index.json")
    if not index_path.exists():
        print("ERROR: index.json missing")
        return 1
    try:
        index = json.loads(index_path.read_text())
    except json.JSONDecodeError as e:
        print(f"ERROR: index.json invalid JSON: {e}")
        return 1

    all_errors: list[str] = []
    total_versions = 0

    for section in ("languages", "tools"):
        section_data = index.get(section, {})
        if not isinstance(section_data, dict):
            all_errors.append(f"index.json:{section} is not an object")
            continue
        for tool_name, meta in section_data.items():
            file_ref = meta.get("file", "")
            claimed_count = meta.get("versions", -1)
            claimed_latest = meta.get("latest", "")

            if file_ref != f"{section}/{tool_name}.json":
                all_errors.append(
                    f"index.json:{section}.{tool_name}.file = {file_ref!r}, "
                    f"expected {section}/{tool_name}.json"
                )

            errors, versions = validate_tool_file(Path(file_ref))
            all_errors.extend(errors)

            actual_count = len(versions)
            if actual_count != claimed_count:
                all_errors.append(
                    f"index.json:{section}.{tool_name}.versions = {claimed_count}, "
                    f"actual = {actual_count}"
                )
            if claimed_latest and claimed_latest not in versions:
                all_errors.append(
                    f"index.json:{section}.{tool_name}.latest = {claimed_latest!r}, "
                    f"not present in {file_ref}"
                )
            total_versions += actual_count

    if all_errors:
        print(f"Validation FAILED with {len(all_errors)} error(s):\n")
        for err in all_errors:
            print(f"  ✗ {err}")
        return 1

    total_tools = sum(len(index.get(s, {})) for s in ("languages", "tools"))
    print(f"✓ Validation passed: {total_tools} tools, {total_versions} versions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
