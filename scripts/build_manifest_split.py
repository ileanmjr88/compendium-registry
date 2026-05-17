#!/usr/bin/env python3
"""
Compendium Registry — Split Manifest Builder

Generates a split manifest structure:
    index.json                            ← index file (small, cached by client)
    languages/go.json                     ← all Go versions
    languages/python.json                 ← all Python versions
    languages/clang.json                  ← all Clang/LLVM versions
    languages/gcc.json                    ← all GCC versions (xPack)
    languages/node.json                   ← all Node.js versions
    languages/arm-none-eabi-gcc.json      ← ARM Cortex-M cross compiler (xPack)
    languages/aarch64-none-elf-gcc.json   ← ARMv8-A bare-metal cross compiler (xPack)
    languages/riscv-none-elf-gcc.json     ← RISC-V cross compiler (xPack)
    tools/cmake.json                      ← all CMake versions
    tools/ninja.json                      ← all Ninja versions
    tools/vcpkg.json                      ← all vcpkg versions
    tools/ccache.json                     ← all ccache versions
    tools/bison.json                      ← GNU Bison (xPack)
    tools/m4.json                         ← GNU M4 (xPack)
    tools/pkg-config.json                 ← pkg-config (xPack)
    tools/realpath.json                   ← realpath (xPack)
    ... etc

Rules:
    - New versions are ADDED, never removed (unless EOL)
    - If a per-tool file already exists, merge new versions into it
    - index.json stays small — just tool names + latest version + file pointer

Run locally (from repo root):
    python3 scripts/build_manifest_split.py

Run in GitHub Actions:
    Same script, triggered by schedule or workflow_dispatch.
"""

import json
import os
import re
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
OUTPUT_DIR = Path(".")  # root of the registry repo
PLATFORMS = {
    "linux": ["amd64", "arm64"],
    "darwin": ["amd64", "arm64"],
}

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def fetch_json(url: str) -> Any:
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "compendium-manifest-builder/0.2")
    if GITHUB_TOKEN and "api.github.com" in url:
        req.add_header("Authorization", f"token {GITHUB_TOKEN}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"  WARNING: HTTP {e.code} fetching {url}")
        return None
    except Exception as e:
        print(f"  WARNING: Error fetching {url}: {e}")
        return None


def fetch_text(url: str) -> str | None:
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "compendium-manifest-builder/0.2")
    if GITHUB_TOKEN and "api.github.com" in url:
        req.add_header("Authorization", f"token {GITHUB_TOKEN}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8")
    except Exception:
        return None


def github_releases(owner: str, repo: str, per_page: int = 30) -> list[dict] | None:
    url = f"https://api.github.com/repos/{owner}/{repo}/releases?per_page={per_page}"
    return fetch_json(url)


def github_latest_tag(owner: str, repo: str) -> str | None:
    """Fetch just the latest release tag (one API call)."""
    data = fetch_json(f"https://api.github.com/repos/{owner}/{repo}/releases/latest")
    if data:
        return data.get("tag_name")
    return None


def load_index() -> dict:
    """Load the existing index.json if it exists."""
    path = OUTPUT_DIR / "index.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def make_artifact(
    url: str,
    checksum: str = "sha256:FILL_IN",
    size: int = 0,
    strip: int = 1,
    link_bin_from: str | None = None,
) -> dict:
    artifact = {"url": url, "checksum": checksum, "size": size, "strip": strip}
    if link_bin_from:
        artifact["link_bin_from"] = link_bin_from
    return artifact


# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------

def load_existing(section: str, tool: str) -> dict:
    """Load existing per-tool JSON file if it exists. Never lose existing versions.
    Returns a flat version map. Handles legacy wrapper format during migration.
    """
    path = OUTPUT_DIR / section / f"{tool}.json"
    if path.exists():
        with open(path) as f:
            data = json.load(f)
        if "versions" in data and ("tool" in data or "section" in data):
            return data["versions"]
        return data
    return {}


def save_tool_file(section: str, tool: str, versions: dict):
    """Save per-tool JSON file as a flat version map."""
    dir_path = OUTPUT_DIR / section
    dir_path.mkdir(parents=True, exist_ok=True)
    path = dir_path / f"{tool}.json"
    with open(path, "w") as f:
        json.dump(versions, f, indent=2)
        f.write("\n")
    print(f"  → wrote {path}")


def merge_versions(existing: dict, new_versions: dict) -> dict:
    """Merge new versions into existing flat version map. Never remove existing versions."""
    merged = dict(existing)
    added = 0
    for version, platforms in new_versions.items():
        if version not in merged:
            merged[version] = platforms
            added += 1
    if added:
        print(f"    + {added} new version(s) added")
    return merged


def get_latest_version(versions: dict) -> str:
    """Get the latest version from a versions dict. Handles semver and date-based."""
    if not versions:
        return ""
    keys = list(versions.keys())
    try:
        from functools import cmp_to_key
        def semver_cmp(a, b):
            def parse(v):
                return [int(x) for x in re.split(r'[-.]', v) if x.isdigit()]
            pa, pb = parse(a), parse(b)
            for x, y in zip(pa, pb):
                if x != y:
                    return x - y
            return len(pa) - len(pb)
        keys.sort(key=cmp_to_key(semver_cmp), reverse=True)
    except Exception:
        keys.sort(reverse=True)
    return keys[0]


# ---------------------------------------------------------------------------
# Fetchers — same as before but return version dicts only
# ---------------------------------------------------------------------------

def fetch_go() -> dict:
    print("Fetching Go versions...")
    data = fetch_json("https://go.dev/dl/?mode=json&include=all")
    if not data:
        return {}

    result = {}
    for release in data:
        version = release["version"].replace("go", "")
        if "rc" in version or "beta" in version:
            continue

        platforms = {}
        for f in release.get("files", []):
            if f["kind"] != "archive":
                continue
            os_name, arch = f["os"], f["arch"]
            if os_name not in PLATFORMS or arch not in PLATFORMS.get(os_name, []):
                continue
            if os_name not in platforms:
                platforms[os_name] = {}
            checksum = f"sha256:{f['sha256']}" if f.get("sha256") else "sha256:FILL_IN"
            platforms[os_name][arch] = make_artifact(
                url=f"https://go.dev/dl/{f['filename']}",
                checksum=checksum,
                size=f.get("size", 0),
                strip=1,
            )

        if platforms:
            result[version] = platforms
            print(f"  ✓ Go {version}")

    return result


def fetch_node() -> dict:
    print("Fetching Node.js versions...")
    data = fetch_json("https://nodejs.org/dist/index.json")
    if not data:
        return {}

    result = {}
    for release in data:
        version = release["version"].lstrip("v")
        major = int(version.split(".")[0])
        if major < 16:
            continue
        if not release.get("lts"):
            continue

        shasums_text = fetch_text(f"https://nodejs.org/dist/v{version}/SHASUMS256.txt")
        checksums = {}
        if shasums_text:
            for line in shasums_text.strip().split("\n"):
                parts = line.split()
                if len(parts) == 2:
                    checksums[parts[1]] = parts[0]

        file_map = {
            ("linux", "amd64"): f"node-v{version}-linux-x64.tar.gz",
            ("linux", "arm64"): f"node-v{version}-linux-arm64.tar.gz",
            ("darwin", "amd64"): f"node-v{version}-darwin-x64.tar.gz",
            ("darwin", "arm64"): f"node-v{version}-darwin-arm64.tar.gz",
        }

        platforms = {}
        for (os_name, arch), filename in file_map.items():
            checksum = f"sha256:{checksums[filename]}" if filename in checksums else "sha256:FILL_IN"
            if os_name not in platforms:
                platforms[os_name] = {}
            platforms[os_name][arch] = make_artifact(
                url=f"https://nodejs.org/dist/v{version}/{filename}",
                checksum=checksum,
                strip=1,
            )

        if platforms:
            result[version] = platforms
            print(f"  ✓ Node.js {version}")

    return result


def fetch_python() -> dict:
    print("Fetching Python versions...")
    releases = github_releases("astral-sh", "python-build-standalone", per_page=10)
    if not releases:
        return {}

    result = {}
    seen = set()
    version_pattern = re.compile(r"cpython-(\d+\.\d+\.\d+)\+")

    for release in releases:
        if release.get("draft") or release.get("prerelease"):
            continue
        assets = {a["name"]: a for a in release.get("assets", [])}

        for name in assets:
            m = version_pattern.search(name)
            if not m:
                continue
            py_version = m.group(1)
            if py_version in seen or "a" in py_version or "b" in py_version or "rc" in py_version:
                continue

            os_arch_keywords = {
                ("linux", "amd64"): ["x86_64-unknown-linux-gnu-install_only"],
                ("linux", "arm64"): ["aarch64-unknown-linux-gnu-install_only"],
                ("darwin", "amd64"): ["x86_64-apple-darwin-install_only"],
                ("darwin", "arm64"): ["aarch64-apple-darwin-install_only"],
            }

            platforms = {}
            for (os_name, arch), keywords in os_arch_keywords.items():
                for asset_name, asset in assets.items():
                    if not asset_name.startswith(f"cpython-{py_version}"):
                        continue
                    if not asset_name.endswith(".tar.gz"):
                        continue
                    if any(kw in asset_name for kw in keywords):
                        sha_name = asset_name + ".sha256"
                        checksum = "sha256:FILL_IN"
                        if sha_name in assets:
                            sha_text = fetch_text(assets[sha_name]["browser_download_url"])
                            if sha_text:
                                checksum = f"sha256:{sha_text.strip().split()[0]}"
                        if os_name not in platforms:
                            platforms[os_name] = {}
                        platforms[os_name][arch] = make_artifact(
                            url=asset["browser_download_url"],
                            checksum=checksum,
                            size=asset.get("size", 0),
                            strip=1,
                        )
                        break

            if platforms:
                result[py_version] = platforms
                seen.add(py_version)
                print(f"  ✓ Python {py_version}")

    return result


def fetch_llvm() -> dict:
    print("Fetching LLVM/Clang versions...")
    releases = github_releases("llvm", "llvm-project", per_page=30)
    if not releases:
        return {}

    result = {}
    for release in releases:
        if release.get("draft") or release.get("prerelease"):
            continue
        tag = release.get("tag_name", "")
        match = re.search(r"llvmorg-(\d+\.\d+\.\d+)", tag)
        if not match:
            continue

        version = match.group(1)
        assets = {a["name"]: a for a in release.get("assets", [])}

        file_map = {
            ("linux", "amd64"): [f"LLVM-{version}-Linux-X64.tar.xz", f"LLVM-{version}-Linux-X86_64.tar.xz"],
            ("linux", "arm64"): [f"LLVM-{version}-Linux-ARM64.tar.xz", f"LLVM-{version}-Linux-AArch64.tar.xz"],
            ("darwin", "arm64"): [f"LLVM-{version}-macOS-ARM64.tar.xz"],
        }

        platforms = {}
        for (os_name, arch), filenames in file_map.items():
            for filename in filenames:
                if filename in assets:
                    asset = assets[filename]
                    if os_name not in platforms:
                        platforms[os_name] = {}
                    platforms[os_name][arch] = make_artifact(
                        url=asset["browser_download_url"],
                        checksum="sha256:FILL_IN",
                        size=asset.get("size", 0),
                        strip=1,
                    )
                    break

        if platforms:
            result[version] = platforms
            print(f"  ✓ LLVM/Clang {version}")

    return result


def resolve_checksums(assets: dict, tag: str, owner: str, repo: str) -> dict:
    """Build a filename→sha256 map from release assets and checksum files.

    Tries, in order:
      1. Companion .sha256 / .sha256sum assets in the release
      2. Common aggregate checksum files (SHA256SUMS, checksums.txt, etc.)
    """
    checksums = {}

    # 1. Companion .sha256 assets (xPack uses .sha; .sha256/.sha256sum cover most others)
    for name, asset in assets.items():
        for suffix in (".sha256", ".sha256sum", ".sha"):
            if name.endswith(suffix):
                base = name[: -len(suffix)]
                sha_text = fetch_text(asset["browser_download_url"])
                if sha_text:
                    checksums[base] = sha_text.strip().split()[0]

    # 2. Aggregate checksum files
    base_url = f"https://github.com/{owner}/{repo}/releases/download/{tag}"
    aggregate_names = [
        "SHA256SUMS", "sha256sums.txt", "checksums.txt",
        # golangci-lint style
        f"{repo}-{tag.lstrip('v')}-checksums.txt",
        # pnpm style
        "SHASUMS256.txt",
    ]
    for cf in aggregate_names:
        if cf in assets:
            text = fetch_text(assets[cf]["browser_download_url"])
        else:
            text = fetch_text(f"{base_url}/{cf}")
        if text:
            for line in text.strip().split("\n"):
                parts = line.strip().split()
                if len(parts) >= 2:
                    h, fname = parts[0], parts[-1]
                    fname = fname.lstrip("*").lstrip("./")
                    if len(h) == 64 and fname not in checksums:
                        checksums[fname] = h

    return checksums


def fetch_github_tool(owner, repo, tool_name, version_regex, file_patterns, strip=1, link_bin_from=None):
    print(f"Fetching {tool_name} versions...")
    releases = github_releases(owner, repo)
    if not releases:
        return {}

    link_bin_from = link_bin_from or {}
    result = {}
    for release in releases:
        if release.get("draft") or release.get("prerelease"):
            continue
        tag = release.get("tag_name", "")
        match = re.search(version_regex, tag)
        if not match:
            continue

        version = match.group(1)
        assets = {a["name"]: a for a in release.get("assets", [])}
        checksums = resolve_checksums(assets, tag, owner, repo)

        platforms = {}
        for (os_name, arch), patterns in file_patterns.items():
            if isinstance(patterns, str):
                patterns = [patterns]
            for pattern in patterns:
                filename = pattern.format(version=version)
                if filename in assets:
                    asset = assets[filename]
                    checksum = f"sha256:{checksums[filename]}" if filename in checksums else "sha256:FILL_IN"
                    if os_name not in platforms:
                        platforms[os_name] = {}
                    platforms[os_name][arch] = make_artifact(
                        url=asset["browser_download_url"],
                        checksum=checksum,
                        size=asset.get("size", 0),
                        strip=strip,
                        link_bin_from=link_bin_from.get((os_name, arch)),
                    )
                    break

        if platforms:
            result[version] = platforms
            print(f"  ✓ {tool_name} {version}")

    return result


def fetch_xpack_tool(repo, tool_name):
    return fetch_github_tool(
        "xpack-dev-tools", repo, tool_name,
        version_regex=r"v(\d+\.\d+\.\d+-\d+(?:\.\d+)?)",
        file_patterns={
            ("linux", "amd64"): [f"xpack-{tool_name}-{{version}}-linux-x64.tar.gz"],
            ("linux", "arm64"): [f"xpack-{tool_name}-{{version}}-linux-arm64.tar.gz"],
            ("darwin", "amd64"): [f"xpack-{tool_name}-{{version}}-darwin-x64.tar.gz"],
            ("darwin", "arm64"): [f"xpack-{tool_name}-{{version}}-darwin-arm64.tar.gz"],
        },
        strip=1,
    )


def fetch_vcpkg() -> dict:
    print("Fetching vcpkg versions...")
    releases = github_releases("microsoft", "vcpkg-tool")
    if not releases:
        return {}

    result = {}
    file_map = {
        ("linux", "amd64"): "vcpkg-glibc",
        ("linux", "arm64"): "vcpkg-glibc-arm64",
        ("darwin", "amd64"): "vcpkg-macos",
        ("darwin", "arm64"): "vcpkg-macos",
    }

    for release in releases:
        if release.get("draft") or release.get("prerelease"):
            continue
        version = release.get("tag_name", "")
        if not re.match(r"\d{4}-\d{2}-\d{2}", version):
            continue
        assets = {a["name"]: a for a in release.get("assets", [])}

        platforms = {}
        for (os_name, arch), filename in file_map.items():
            if filename not in assets:
                continue
            asset = assets[filename]
            if os_name not in platforms:
                platforms[os_name] = {}
            platforms[os_name][arch] = make_artifact(
                url=asset["browser_download_url"],
                checksum="sha256:FILL_IN",
                size=asset.get("size", 0),
                strip=0,
            )

        if platforms:
            result[version] = platforms
            print(f"  ✓ vcpkg {version}")

    return result


# ---------------------------------------------------------------------------
# Build all tools
# ---------------------------------------------------------------------------

def check_github_latest(owner: str, repo: str, version_regex: str, known_latest: str) -> bool:
    """Return True if upstream has a newer version than known_latest."""
    tag = github_latest_tag(owner, repo)
    if not tag:
        return True  # can't tell, fetch to be safe
    match = re.search(version_regex, tag)
    if not match:
        return True
    upstream = match.group(1)
    if upstream == known_latest:
        print(f"  ✓ up to date ({known_latest})")
        return False
    print(f"  ↑ new version available: {upstream} (have {known_latest})")
    return True


def build_all():
    print("=" * 60)
    print("Compendium Registry — Split Manifest Builder")
    print("=" * 60)
    print()

    existing_index = load_index()

    def known_latest(section: str, tool: str) -> str:
        """Get the latest version we already have from the index."""
        return existing_index.get(section, {}).get(tool, {}).get("latest", "")

    def update_tool(section: str, tool: str, new_versions: dict):
        """Merge new versions into existing and save."""
        if new_versions:
            existing = load_existing(section, tool)
            merged = merge_versions(existing, new_versions)
            save_tool_file(section, tool, merged)

    # === Languages ===
    # Go — check go.dev for latest stable
    print("go:")
    go_latest = known_latest("languages", "go")
    go_check = fetch_json("https://go.dev/dl/?mode=json")
    go_upstream = None
    if go_check:
        for r in go_check:
            v = r["version"].replace("go", "")
            if "rc" not in v and "beta" not in v:
                go_upstream = v
                break
    if go_upstream and go_upstream == go_latest:
        print(f"  ✓ up to date ({go_latest})")
    else:
        if go_upstream:
            print(f"  ↑ new version available: {go_upstream} (have {go_latest})")
        update_tool("languages", "go", fetch_go())

    # Node — check nodejs.org for latest LTS
    print("node:")
    node_latest = known_latest("languages", "node")
    node_check = fetch_json("https://nodejs.org/dist/index.json")
    node_upstream = None
    if node_check:
        for r in node_check:
            if r.get("lts"):
                node_upstream = r["version"].lstrip("v")
                break
    if node_upstream and node_upstream == node_latest:
        print(f"  ✓ up to date ({node_latest})")
    else:
        if node_upstream:
            print(f"  ↑ new version available: {node_upstream} (have {node_latest})")
        update_tool("languages", "node", fetch_node())

    # Python — astral-sh/python-build-standalone (date-based tags, check cpython version in assets)
    print("python:")
    py_latest = known_latest("languages", "python")
    py_release = fetch_json("https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest")
    py_upstream = None
    if py_release:
        for a in py_release.get("assets", []):
            m = re.search(r"cpython-(\d+\.\d+\.\d+)\+", a["name"])
            if m:
                py_upstream = m.group(1)
                break
    if py_upstream and py_upstream == py_latest:
        print(f"  ✓ up to date ({py_latest})")
    else:
        if py_upstream:
            print(f"  ↑ new version available: {py_upstream} (have {py_latest})")
        update_tool("languages", "python", fetch_python())

    # Clang/LLVM
    print("clang:")
    if check_github_latest("llvm", "llvm-project", r"llvmorg-(\d+\.\d+\.\d+)", known_latest("languages", "clang")):
        update_tool("languages", "clang", fetch_llvm())

    # GCC (xPack)
    print("gcc:")
    if check_github_latest("xpack-dev-tools", "gcc-xpack", r"v(\d+\.\d+\.\d+-\d+(?:\.\d+)?)", known_latest("languages", "gcc")):
        update_tool("languages", "gcc", fetch_xpack_tool("gcc-xpack", "gcc"))

    # arm-none-eabi-gcc (xPack) — C/C++ cross-compiler for ARM Cortex-M
    print("arm-none-eabi-gcc:")
    if check_github_latest("xpack-dev-tools", "arm-none-eabi-gcc-xpack", r"v(\d+\.\d+\.\d+-\d+(?:\.\d+)?)", known_latest("languages", "arm-none-eabi-gcc")):
        update_tool("languages", "arm-none-eabi-gcc", fetch_xpack_tool("arm-none-eabi-gcc-xpack", "arm-none-eabi-gcc"))

    # aarch64-none-elf-gcc (xPack) — C/C++ cross-compiler for ARMv8-A bare-metal
    print("aarch64-none-elf-gcc:")
    if check_github_latest("xpack-dev-tools", "aarch64-none-elf-gcc-xpack", r"v(\d+\.\d+\.\d+-\d+(?:\.\d+)?)", known_latest("languages", "aarch64-none-elf-gcc")):
        update_tool("languages", "aarch64-none-elf-gcc", fetch_xpack_tool("aarch64-none-elf-gcc-xpack", "aarch64-none-elf-gcc"))

    # riscv-none-elf-gcc (xPack) — C/C++ cross-compiler for RISC-V
    print("riscv-none-elf-gcc:")
    if check_github_latest("xpack-dev-tools", "riscv-none-elf-gcc-xpack", r"v(\d+\.\d+\.\d+-\d+(?:\.\d+)?)", known_latest("languages", "riscv-none-elf-gcc")):
        update_tool("languages", "riscv-none-elf-gcc", fetch_xpack_tool("riscv-none-elf-gcc-xpack", "riscv-none-elf-gcc"))

    # === Tools ===
    # Each entry: (tool_name, owner, repo, version_regex, fetcher)
    github_tools = [
        ("cmake", "Kitware", "CMake", r"v(\d+\.\d+\.\d+)", lambda: fetch_github_tool(
            "Kitware", "CMake", "CMake", r"v(\d+\.\d+\.\d+)",
            {
                ("linux", "amd64"): "cmake-{version}-linux-x86_64.tar.gz",
                ("linux", "arm64"): "cmake-{version}-linux-aarch64.tar.gz",
                ("darwin", "amd64"): "cmake-{version}-macos-universal.tar.gz",
                ("darwin", "arm64"): "cmake-{version}-macos-universal.tar.gz",
            },
            strip=1,
            link_bin_from={
                ("darwin", "amd64"): "CMake.app/Contents/bin",
                ("darwin", "arm64"): "CMake.app/Contents/bin",
            })),
        ("ninja", "ninja-build", "ninja", r"v(\d+\.\d+\.\d+)", lambda: fetch_github_tool(
            "ninja-build", "ninja", "Ninja", r"v(\d+\.\d+\.\d+)",
            {
                ("linux", "amd64"): "ninja-linux.zip",
                ("linux", "arm64"): "ninja-linux-aarch64.zip",
                ("darwin", "amd64"): "ninja-mac.zip",
                ("darwin", "arm64"): "ninja-mac.zip",
            }, strip=0)),
        ("ccache", "ccache", "ccache", r"v(\d+\.\d+(?:\.\d+)?)", lambda: fetch_github_tool(
            "ccache", "ccache", "ccache", r"v(\d+\.\d+(?:\.\d+)?)",
            {
                ("linux", "amd64"): ["ccache-{version}-linux-x86_64.tar.xz", "ccache-{version}-linux-x86_64-glibc.tar.gz"],
                ("linux", "arm64"): ["ccache-{version}-linux-aarch64.tar.xz", "ccache-{version}-linux-aarch64-glibc.tar.gz"],
                ("darwin", "amd64"): "ccache-{version}-darwin.tar.gz",
                ("darwin", "arm64"): "ccache-{version}-darwin.tar.gz",
            }, strip=1)),
        ("golangci-lint", "golangci", "golangci-lint", r"v(\d+\.\d+\.\d+)", lambda: fetch_github_tool(
            "golangci", "golangci-lint", "golangci-lint", r"v(\d+\.\d+\.\d+)",
            {
                ("linux", "amd64"): "golangci-lint-{version}-linux-amd64.tar.gz",
                ("linux", "arm64"): "golangci-lint-{version}-linux-arm64.tar.gz",
                ("darwin", "amd64"): "golangci-lint-{version}-darwin-amd64.tar.gz",
                ("darwin", "arm64"): "golangci-lint-{version}-darwin-arm64.tar.gz",
            }, strip=1)),
        ("goreleaser", "goreleaser", "goreleaser", r"v(\d+\.\d+\.\d+)", lambda: fetch_github_tool(
            "goreleaser", "goreleaser", "goreleaser", r"v(\d+\.\d+\.\d+)",
            {
                ("linux", "amd64"): "goreleaser_Linux_x86_64.tar.gz",
                ("linux", "arm64"): "goreleaser_Linux_arm64.tar.gz",
                ("darwin", "amd64"): "goreleaser_Darwin_x86_64.tar.gz",
                ("darwin", "arm64"): "goreleaser_Darwin_arm64.tar.gz",
            }, strip=0)),
        ("uv", "astral-sh", "uv", r"(\d+\.\d+\.\d+)", lambda: fetch_github_tool(
            "astral-sh", "uv", "uv", r"(\d+\.\d+\.\d+)",
            {
                ("linux", "amd64"): "uv-x86_64-unknown-linux-gnu.tar.gz",
                ("linux", "arm64"): "uv-aarch64-unknown-linux-gnu.tar.gz",
                ("darwin", "amd64"): "uv-x86_64-apple-darwin.tar.gz",
                ("darwin", "arm64"): "uv-aarch64-apple-darwin.tar.gz",
            }, strip=1)),
        ("ruff", "astral-sh", "ruff", r"(\d+\.\d+\.\d+)", lambda: fetch_github_tool(
            "astral-sh", "ruff", "Ruff", r"(\d+\.\d+\.\d+)",
            {
                ("linux", "amd64"): "ruff-x86_64-unknown-linux-gnu.tar.gz",
                ("linux", "arm64"): "ruff-aarch64-unknown-linux-gnu.tar.gz",
                ("darwin", "amd64"): "ruff-x86_64-apple-darwin.tar.gz",
                ("darwin", "arm64"): "ruff-aarch64-apple-darwin.tar.gz",
            }, strip=1)),
        ("pnpm", "pnpm", "pnpm", r"v(\d+\.\d+\.\d+)", lambda: fetch_github_tool(
            "pnpm", "pnpm", "pnpm", r"v(\d+\.\d+\.\d+)",
            {
                ("linux", "amd64"): "pnpm-linux-x64",
                ("linux", "arm64"): "pnpm-linux-arm64",
                ("darwin", "amd64"): "pnpm-macos-x64",
                ("darwin", "arm64"): "pnpm-macos-arm64",
            }, strip=0)),
        ("openocd", "xpack-dev-tools", "openocd-xpack", r"v(\d+\.\d+\.\d+-\d+(?:\.\d+)?)",
            lambda: fetch_xpack_tool("openocd-xpack", "openocd")),
        ("bison", "xpack-dev-tools", "bison-xpack", r"v(\d+\.\d+\.\d+-\d+(?:\.\d+)?)",
            lambda: fetch_xpack_tool("bison-xpack", "bison")),
        ("m4", "xpack-dev-tools", "m4-xpack", r"v(\d+\.\d+\.\d+-\d+(?:\.\d+)?)",
            lambda: fetch_xpack_tool("m4-xpack", "m4")),
        ("pkg-config", "xpack-dev-tools", "pkg-config-xpack", r"v(\d+\.\d+\.\d+-\d+(?:\.\d+)?)",
            lambda: fetch_xpack_tool("pkg-config-xpack", "pkg-config")),
        ("realpath", "xpack-dev-tools", "realpath-xpack", r"v(\d+\.\d+\.\d+-\d+(?:\.\d+)?)",
            lambda: fetch_xpack_tool("realpath-xpack", "realpath")),
        ("vcpkg", "microsoft", "vcpkg-tool", r"(\d{4}-\d{2}-\d{2})", fetch_vcpkg),
    ]

    for tool_name, owner, repo, ver_regex, fetcher in github_tools:
        print(f"{tool_name}:")
        if check_github_latest(owner, repo, ver_regex, known_latest("tools", tool_name)):
            update_tool("tools", tool_name, fetcher())

    # === Build index.json ===
    print()
    print("=" * 60)
    print("Building index.json")
    print("=" * 60)

    index = {
        "version": "2",
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "languages": {},
        "tools": {},
    }

    for section in ["languages", "tools"]:
        section_dir = OUTPUT_DIR / section
        if not section_dir.exists():
            continue
        for f in sorted(section_dir.glob("*.json")):
            tool_name = f.stem
            with open(f) as fh:
                data = json.load(fh)
            version_count = len(data)
            latest = get_latest_version(data)
            index[section][tool_name] = {
                "latest": latest,
                "versions": version_count,
                "file": f"{section}/{tool_name}.json",
            }
            print(f"  {tool_name}: {version_count} versions, latest {latest}")

    index_path = OUTPUT_DIR / "index.json"
    with open(index_path, "w") as f:
        json.dump(index, f, indent=2)
        f.write("\n")

    print()
    total_tools = len(index["languages"]) + len(index["tools"])
    total_versions = sum(t["versions"] for t in index["languages"].values()) + \
                     sum(t["versions"] for t in index["tools"].values())
    print(f"✓ Registry: {total_tools} tools, {total_versions} total versions")
    print(f"✓ Index written to {index_path}")


if __name__ == "__main__":
    build_all()
