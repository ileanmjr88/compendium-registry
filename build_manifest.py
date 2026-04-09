#!/usr/bin/env python3
"""
Compendium Registry — Manifest Builder

Fetches latest versions, download URLs, and checksums from official sources
and GitHub Releases APIs. Outputs a manifest.json for the Compendium registry.

Run locally:
    python3 build_manifest.py

Run in GitHub Actions:
    Same script, triggered by schedule or workflow_dispatch.

Sources:
    - Go:                go.dev/dl/?mode=json (official JSON API)
    - Node.js:           nodejs.org/dist/index.json (official JSON API)
    - Python:            astral-sh/python-build-standalone (GitHub Releases)
    - GCC:               xpack-dev-tools/gcc-xpack (GitHub Releases)
    - Clang/LLVM:        llvm/llvm-project (GitHub Releases)
    - arm-none-eabi-gcc: xpack-dev-tools/arm-none-eabi-gcc-xpack (GitHub Releases)
    - riscv-none-elf-gcc:xpack-dev-tools/riscv-none-elf-gcc-xpack (GitHub Releases)
    - CMake:             Kitware/CMake (GitHub Releases)
    - Ninja:             ninja-build/ninja (GitHub Releases)
    - Make:              xpack-dev-tools/make-xpack (GitHub Releases)
    - OpenOCD:           xpack-dev-tools/openocd-xpack (GitHub Releases)
    - ccache:            ccache/ccache (GitHub Releases)
    - cppcheck:          danmar/cppcheck (GitHub Releases)
    - Doxygen:           doxygen/doxygen (GitHub Releases)
    - golangci-lint:     golangci/golangci-lint (GitHub Releases)
    - delve:             go-delve/delve (GitHub Releases)
    - uv:                astral-sh/uv (GitHub Releases)
    - ruff:              astral-sh/ruff (GitHub Releases)
    - pnpm:              pnpm/pnpm (GitHub Releases)
    - vcpkg:             microsoft/vcpkg (GitHub Releases — needs build)
    - Valgrind:          valgrind (source only — needs build)
    - pkg-config:        pkgconf/pkgconf (GitHub Releases)
"""

import json
import hashlib
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# GitHub token for API rate limits (optional, but recommended)
# Set GITHUB_TOKEN env var or leave empty for unauthenticated (60 req/hr)
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# How many latest stable versions to include per tool
MAX_VERSIONS = 6

# Platforms and architectures we support
PLATFORMS = {
    "linux": ["amd64", "arm64"],
    "darwin": ["amd64", "arm64"],
}

# Output file
OUTPUT_FILE = "manifest.json"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def fetch_json(url: str) -> Any:
    """Fetch JSON from a URL."""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "compendium-manifest-builder/0.1")
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
    """Fetch text content from a URL."""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "compendium-manifest-builder/0.1")
    if GITHUB_TOKEN and "api.github.com" in url:
        req.add_header("Authorization", f"token {GITHUB_TOKEN}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8")
    except Exception as e:
        print(f"  WARNING: Error fetching {url}: {e}")
        return None


def github_releases(owner: str, repo: str, per_page: int = 20) -> list[dict] | None:
    """Fetch releases from GitHub API."""
    url = f"https://api.github.com/repos/{owner}/{repo}/releases?per_page={per_page}"
    return fetch_json(url)


# ---------------------------------------------------------------------------
# Artifact helper
# ---------------------------------------------------------------------------

def make_artifact(url: str, checksum: str = "sha256:FILL_IN", size: int = 0, strip: int = 1) -> dict:
    """Create an artifact entry."""
    return {
        "url": url,
        "checksum": checksum,
        "size": size,
        "strip": strip,
    }


# ---------------------------------------------------------------------------
# Go — go.dev/dl/?mode=json
# ---------------------------------------------------------------------------

def fetch_go() -> dict:
    """Fetch Go versions from official API."""
    print("Fetching Go versions...")
    data = fetch_json("https://go.dev/dl/?mode=json&include=all")
    if not data:
        return {}

    result = {}
    count = 0

    for release in data:
        if count >= MAX_VERSIONS:
            break

        version = release["version"].replace("go", "")  # "go1.22.1" -> "1.22.1"
        if "rc" in version or "beta" in version:
            continue

        platforms = {}
        for f in release.get("files", []):
            if f["kind"] != "archive":
                continue

            os_name = f["os"]
            arch = f["arch"]

            # Normalize
            if os_name == "darwin":
                os_name = "darwin"
            if arch == "amd64":
                pass  # already canonical
            elif arch == "arm64":
                pass  # already canonical
            else:
                continue

            if os_name not in PLATFORMS:
                continue
            if arch not in PLATFORMS[os_name]:
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
            count += 1
            print(f"  ✓ Go {version}")

    return result


# ---------------------------------------------------------------------------
# Node.js — nodejs.org/dist/index.json
# ---------------------------------------------------------------------------

def fetch_node() -> dict:
    """Fetch Node.js versions from official API."""
    print("Fetching Node.js versions...")
    data = fetch_json("https://nodejs.org/dist/index.json")
    if not data:
        return {}

    result = {}
    count = 0

    for release in data:
        if count >= MAX_VERSIONS:
            break

        version = release["version"].lstrip("v")  # "v20.11.0" -> "20.11.0"

        # Only LTS or current stable
        if not release.get("lts") and count > 0:
            continue

        # Fetch checksums
        shasums_url = f"https://nodejs.org/dist/v{version}/SHASUMS256.txt"
        shasums_text = fetch_text(shasums_url)
        checksums = {}
        if shasums_text:
            for line in shasums_text.strip().split("\n"):
                parts = line.split()
                if len(parts) == 2:
                    checksums[parts[1]] = parts[0]

        # Map files to platforms
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
            count += 1
            print(f"  ✓ Node.js {version}")

    return result


# ---------------------------------------------------------------------------
# GitHub Releases — generic fetcher for xPack and other projects
# ---------------------------------------------------------------------------

def fetch_github_tool(
    owner: str,
    repo: str,
    tool_name: str,
    version_regex: str,
    file_patterns: dict[tuple[str, str], str | list[str]],
    strip: int = 1,
    checksum_suffix: str = ".sha256",
) -> dict:
    """
    Generic GitHub Releases fetcher.

    Args:
        owner: GitHub org/user
        repo: GitHub repo name
        tool_name: Display name
        version_regex: Regex to extract version from tag name (first group)
        file_patterns: Map of (os, arch) -> filename pattern(s) with {version} placeholder
        strip: Strip level for tar extraction
        checksum_suffix: Suffix for checksum companion file (e.g., ".sha256")
    """
    print(f"Fetching {tool_name} versions...")
    releases = github_releases(owner, repo)
    if not releases:
        return {}

    result = {}
    count = 0

    for release in releases:
        if count >= MAX_VERSIONS:
            break
        if release.get("draft") or release.get("prerelease"):
            continue

        tag = release.get("tag_name", "")
        match = re.search(version_regex, tag)
        if not match:
            continue

        version = match.group(1)
        assets = {a["name"]: a for a in release.get("assets", [])}

        # Build checksum map from .sha256 companion files
        checksums = {}
        for asset_name, asset in assets.items():
            if asset_name.endswith(checksum_suffix):
                base_name = asset_name[: -len(checksum_suffix)]
                sha_text = fetch_text(asset["browser_download_url"])
                if sha_text:
                    # Some .sha256 files have just the hash, others have "hash  filename"
                    sha_hash = sha_text.strip().split()[0]
                    checksums[base_name] = sha_hash

        platforms = {}
        for (os_name, arch), patterns in file_patterns.items():
            if isinstance(patterns, str):
                patterns = [patterns]

            found = False
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
                    )
                    found = True
                    break

            if not found:
                # Try fuzzy match — look for assets containing os and arch keywords
                os_keywords = {"linux": ["linux"], "darwin": ["darwin", "macos", "osx"]}
                arch_keywords = {"amd64": ["x64", "x86_64", "amd64"], "arm64": ["arm64", "aarch64"]}

                for asset_name, asset in assets.items():
                    if asset_name.endswith(checksum_suffix):
                        continue
                    if not (asset_name.endswith(".tar.gz") or asset_name.endswith(".tar.xz") or asset_name.endswith(".zip")):
                        continue

                    name_lower = asset_name.lower()
                    os_match = any(kw in name_lower for kw in os_keywords.get(os_name, []))
                    arch_match = any(kw in name_lower for kw in arch_keywords.get(arch, []))

                    if os_match and arch_match:
                        checksum = f"sha256:{checksums[asset_name]}" if asset_name in checksums else "sha256:FILL_IN"
                        if os_name not in platforms:
                            platforms[os_name] = {}
                        platforms[os_name][arch] = make_artifact(
                            url=asset["browser_download_url"],
                            checksum=checksum,
                            size=asset.get("size", 0),
                            strip=strip,
                        )
                        break

        if platforms:
            result[version] = platforms
            count += 1
            print(f"  ✓ {tool_name} {version}")

    return result


# ---------------------------------------------------------------------------
# Python — astral-sh/python-build-standalone
# ---------------------------------------------------------------------------

def fetch_python() -> dict:
    """Fetch Python standalone builds from Astral."""
    print("Fetching Python versions...")
    releases = github_releases("astral-sh", "python-build-standalone", per_page=10)
    if not releases:
        return {}

    result = {}
    count = 0

    # python-build-standalone releases are named by date (e.g., "20240224")
    # Assets contain the Python version in the filename
    # e.g., cpython-3.12.2+20240224-x86_64-unknown-linux-gnu-install_only.tar.gz

    seen_versions = set()

    for release in releases:
        if count >= MAX_VERSIONS:
            break
        if release.get("draft") or release.get("prerelease"):
            continue

        assets = {a["name"]: a for a in release.get("assets", [])}

        # Find Python versions in this release
        version_pattern = re.compile(r"cpython-(\d+\.\d+\.\d+)\+")
        py_versions_in_release = set()
        for name in assets:
            m = version_pattern.search(name)
            if m:
                py_versions_in_release.add(m.group(1))

        for py_version in sorted(py_versions_in_release, reverse=True):
            if count >= MAX_VERSIONS:
                break
            if py_version in seen_versions:
                continue

            # Skip pre-release Python versions
            if "a" in py_version or "b" in py_version or "rc" in py_version:
                continue

            # Map to our platforms
            file_map = {
                ("linux", "amd64"): f"cpython-{py_version}",
                ("linux", "arm64"): f"cpython-{py_version}",
                ("darwin", "amd64"): f"cpython-{py_version}",
                ("darwin", "arm64"): f"cpython-{py_version}",
            }

            os_arch_keywords = {
                ("linux", "amd64"): ["x86_64-unknown-linux-gnu-install_only", "x86_64-unknown-linux-gnu-pgo+lto-full"],
                ("linux", "arm64"): ["aarch64-unknown-linux-gnu-install_only", "aarch64-unknown-linux-gnu-pgo+lto-full"],
                ("darwin", "amd64"): ["x86_64-apple-darwin-install_only", "x86_64-apple-darwin-pgo+lto-full"],
                ("darwin", "arm64"): ["aarch64-apple-darwin-install_only", "aarch64-apple-darwin-pgo+lto-full"],
            }

            platforms = {}
            for (os_name, arch), keywords in os_arch_keywords.items():
                for asset_name, asset in assets.items():
                    if not asset_name.startswith(f"cpython-{py_version}"):
                        continue
                    if not asset_name.endswith(".tar.gz"):
                        continue
                    if any(kw in asset_name for kw in keywords):
                        # Check for .sha256 companion
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
                seen_versions.add(py_version)
                count += 1
                print(f"  ✓ Python {py_version}")

    return result


# ---------------------------------------------------------------------------
# vcpkg — microsoft/vcpkg-tool
# ---------------------------------------------------------------------------

def fetch_vcpkg() -> dict:
    """Fetch vcpkg pre-built binaries from microsoft/vcpkg-tool releases.

    vcpkg-tool publishes standalone binaries (not archives) with date-based
    version tags (e.g., "2026-04-06").  Assets:
      - vcpkg-glibc         (linux amd64)
      - vcpkg-glibc-arm64   (linux arm64)
      - vcpkg-macos          (darwin universal)
    """
    print("Fetching vcpkg versions...")
    releases = github_releases("microsoft", "vcpkg-tool")
    if not releases:
        return {}

    result = {}
    count = 0

    file_map = {
        ("linux", "amd64"): "vcpkg-glibc",
        ("linux", "arm64"): "vcpkg-glibc-arm64",
        ("darwin", "amd64"): "vcpkg-macos",
        ("darwin", "arm64"): "vcpkg-macos",
    }

    for release in releases:
        if count >= MAX_VERSIONS:
            break
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

            # Check for .sig companion (no .sha256 files available)
            checksum = "sha256:FILL_IN"

            if os_name not in platforms:
                platforms[os_name] = {}
            platforms[os_name][arch] = make_artifact(
                url=asset["browser_download_url"],
                checksum=checksum,
                size=asset.get("size", 0),
                strip=0,
            )

        if platforms:
            result[version] = platforms
            count += 1
            print(f"  ✓ vcpkg {version}")

    return result


# ---------------------------------------------------------------------------
# Tool definitions — all the GitHub-based tools
# ---------------------------------------------------------------------------

def fetch_all_tools() -> dict[str, dict]:
    """Fetch all tools from their respective sources."""
    tools = {}

    # CMake — Kitware/CMake
    data = fetch_github_tool(
        "Kitware", "CMake", "CMake",
        version_regex=r"v(\d+\.\d+\.\d+)",
        file_patterns={
            ("linux", "amd64"): "cmake-{version}-linux-x86_64.tar.gz",
            ("linux", "arm64"): "cmake-{version}-linux-aarch64.tar.gz",
            ("darwin", "amd64"): "cmake-{version}-macos-universal.tar.gz",
            ("darwin", "arm64"): "cmake-{version}-macos-universal.tar.gz",
        },
        strip=1,
    )
    if data:
        tools["cmake"] = data

    # Ninja — ninja-build/ninja
    data = fetch_github_tool(
        "ninja-build", "ninja", "Ninja",
        version_regex=r"v(\d+\.\d+\.\d+)",
        file_patterns={
            ("linux", "amd64"): "ninja-linux.zip",
            ("linux", "arm64"): "ninja-linux-aarch64.zip",
            ("darwin", "amd64"): "ninja-mac.zip",
            ("darwin", "arm64"): "ninja-mac.zip",
        },
        strip=0,  # ninja ships as a single binary in a zip
    )
    if data:
        tools["ninja"] = data

    # ccache — ccache/ccache
    data = fetch_github_tool(
        "ccache", "ccache", "ccache",
        version_regex=r"v(\d+\.\d+(?:\.\d+)?)",
        file_patterns={
            ("linux", "amd64"): "ccache-{version}-linux-x86_64.tar.xz",
            ("linux", "arm64"): "ccache-{version}-linux-aarch64.tar.xz",
            ("darwin", "amd64"): "ccache-{version}-darwin.tar.gz",
            ("darwin", "arm64"): "ccache-{version}-darwin.tar.gz",
        },
        strip=1,
    )
    if data:
        tools["ccache"] = data

    # cppcheck — danmar/cppcheck
    data = fetch_github_tool(
        "danmar", "cppcheck", "cppcheck",
        version_regex=r"(\d+\.\d+(?:\.\d+)?)",
        file_patterns={},  # will rely on fuzzy matching
        strip=1,
    )
    if data:
        tools["cppcheck"] = data

    # Doxygen — doxygen/doxygen
    data = fetch_github_tool(
        "doxygen", "doxygen", "Doxygen",
        version_regex=r"Release_(\d+_\d+_\d+)",
        file_patterns={
            ("linux", "amd64"): "doxygen-{version}.linux.bin.tar.gz",
            ("darwin", "amd64"): "Doxygen-{version}.dmg",
            ("darwin", "arm64"): "Doxygen-{version}.dmg",
        },
        strip=1,
    )
    if data:
        # Fix version format: "1_10_0" -> "1.10.0"
        fixed = {}
        for v, platforms in data.items():
            fixed[v.replace("_", ".")] = platforms
        tools["doxygen"] = fixed

    # golangci-lint — golangci/golangci-lint
    data = fetch_github_tool(
        "golangci", "golangci-lint", "golangci-lint",
        version_regex=r"v(\d+\.\d+\.\d+)",
        file_patterns={
            ("linux", "amd64"): "golangci-lint-{version}-linux-amd64.tar.gz",
            ("linux", "arm64"): "golangci-lint-{version}-linux-arm64.tar.gz",
            ("darwin", "amd64"): "golangci-lint-{version}-darwin-amd64.tar.gz",
            ("darwin", "arm64"): "golangci-lint-{version}-darwin-arm64.tar.gz",
        },
        strip=1,
    )
    if data:
        tools["golangci-lint"] = data

    # delve — go-delve/delve
    data = fetch_github_tool(
        "go-delve", "delve", "Delve",
        version_regex=r"v(\d+\.\d+\.\d+)",
        file_patterns={},  # delve doesn't ship pre-built binaries on GitHub Releases
        strip=1,
    )
    if data:
        tools["delve"] = data

    # uv — astral-sh/uv
    data = fetch_github_tool(
        "astral-sh", "uv", "uv",
        version_regex=r"(\d+\.\d+\.\d+)",
        file_patterns={
            ("linux", "amd64"): "uv-x86_64-unknown-linux-gnu.tar.gz",
            ("linux", "arm64"): "uv-aarch64-unknown-linux-gnu.tar.gz",
            ("darwin", "amd64"): "uv-x86_64-apple-darwin.tar.gz",
            ("darwin", "arm64"): "uv-aarch64-apple-darwin.tar.gz",
        },
        strip=0,
    )
    if data:
        tools["uv"] = data

    # ruff — astral-sh/ruff
    data = fetch_github_tool(
        "astral-sh", "ruff", "Ruff",
        version_regex=r"(\d+\.\d+\.\d+)",
        file_patterns={
            ("linux", "amd64"): "ruff-x86_64-unknown-linux-gnu.tar.gz",
            ("linux", "arm64"): "ruff-aarch64-unknown-linux-gnu.tar.gz",
            ("darwin", "amd64"): "ruff-x86_64-apple-darwin.tar.gz",
            ("darwin", "arm64"): "ruff-aarch64-apple-darwin.tar.gz",
        },
        strip=0,
    )
    if data:
        tools["ruff"] = data

    # pnpm — pnpm/pnpm
    data = fetch_github_tool(
        "pnpm", "pnpm", "pnpm",
        version_regex=r"v(\d+\.\d+\.\d+)",
        file_patterns={
            ("linux", "amd64"): "pnpm-linux-x64",
            ("linux", "arm64"): "pnpm-linux-arm64",
            ("darwin", "amd64"): "pnpm-macos-x64",
            ("darwin", "arm64"): "pnpm-macos-arm64",
        },
        strip=0,
    )
    if data:
        tools["pnpm"] = data

    # vcpkg — microsoft/vcpkg-tool
    data = fetch_vcpkg()
    if data:
        tools["vcpkg"] = data

    # pkg-config via pkgconf — pkgconf/pkgconf
    data = fetch_github_tool(
        "pkgconf", "pkgconf", "pkgconf",
        version_regex=r"pkgconf-(\d+\.\d+\.\d+)",
        file_patterns={},  # source only, will need build
        strip=1,
    )
    if data:
        tools["pkgconf"] = data

    return tools


# ---------------------------------------------------------------------------
# xPack tools — specific patterns
# ---------------------------------------------------------------------------

def fetch_xpack_tool(repo: str, tool_name: str) -> dict:
    """Fetch an xPack tool from GitHub Releases."""
    return fetch_github_tool(
        "xpack-dev-tools", repo, tool_name,
        version_regex=r"v(\d+\.\d+\.\d+-\d+\.\d+)",
        file_patterns={
            ("linux", "amd64"): [
                f"xpack-{tool_name}-{{version}}-linux-x64.tar.gz",
            ],
            ("linux", "arm64"): [
                f"xpack-{tool_name}-{{version}}-linux-arm64.tar.gz",
            ],
            ("darwin", "amd64"): [
                f"xpack-{tool_name}-{{version}}-darwin-x64.tar.gz",
            ],
            ("darwin", "arm64"): [
                f"xpack-{tool_name}-{{version}}-darwin-arm64.tar.gz",
            ],
        },
        strip=2,  # xPack needs strip 2
    )


def fetch_all_xpack() -> dict[str, dict]:
    """Fetch all xPack-sourced tools."""
    xpack_tools = {}

    # GCC
    data = fetch_xpack_tool("gcc-xpack", "gcc")
    if data:
        xpack_tools["gcc"] = data

    # arm-none-eabi-gcc
    data = fetch_xpack_tool("arm-none-eabi-gcc-xpack", "arm-none-eabi-gcc")
    if data:
        xpack_tools["arm-none-eabi-gcc"] = data

    # riscv-none-elf-gcc
    data = fetch_xpack_tool("riscv-none-elf-gcc-xpack", "riscv-none-elf-gcc")
    if data:
        xpack_tools["riscv-none-elf-gcc"] = data

    # Make
    data = fetch_xpack_tool("make-xpack", "make")
    if data:
        xpack_tools["make"] = data

    # OpenOCD
    data = fetch_xpack_tool("openocd-xpack", "openocd")
    if data:
        xpack_tools["openocd"] = data

    return xpack_tools


# ---------------------------------------------------------------------------
# LLVM/Clang
# ---------------------------------------------------------------------------

def fetch_llvm() -> dict:
    """Fetch LLVM/Clang releases."""
    print("Fetching LLVM/Clang versions...")
    releases = github_releases("llvm", "llvm-project", per_page=20)
    if not releases:
        return {}

    result = {}
    count = 0

    for release in releases:
        if count >= MAX_VERSIONS:
            break
        if release.get("draft") or release.get("prerelease"):
            continue

        tag = release.get("tag_name", "")
        match = re.search(r"llvmorg-(\d+\.\d+\.\d+)", tag)
        if not match:
            continue

        version = match.group(1)
        assets = {a["name"]: a for a in release.get("assets", [])}

        # LLVM file naming convention
        file_map = {
            ("linux", "amd64"): [
                f"clang+llvm-{version}-x86_64-linux-gnu-ubuntu-",
                f"LLVM-{version}-Linux-X64.tar.xz",
                f"LLVM-{version}-Linux.tar.xz",
            ],
            ("linux", "arm64"): [
                f"clang+llvm-{version}-aarch64-linux-gnu",
                f"LLVM-{version}-Linux-AArch64.tar.xz",
            ],
            ("darwin", "amd64"): [
                f"clang+llvm-{version}-x86_64-apple-darwin",
                f"LLVM-{version}-macOS-X64.tar.xz",
            ],
            ("darwin", "arm64"): [
                f"clang+llvm-{version}-arm64-apple-darwin",
                f"LLVM-{version}-macOS-ARM64.tar.xz",
            ],
        }

        platforms = {}
        for (os_name, arch), prefixes in file_map.items():
            for prefix in prefixes:
                for asset_name, asset in assets.items():
                    if asset_name.startswith(prefix) and (
                        asset_name.endswith(".tar.xz") or asset_name.endswith(".tar.gz")
                    ):
                        if os_name not in platforms:
                            platforms[os_name] = {}
                        platforms[os_name][arch] = make_artifact(
                            url=asset["browser_download_url"],
                            checksum="sha256:FILL_IN",
                            size=asset.get("size", 0),
                            strip=1,
                        )
                        break
                if os_name in platforms and arch in platforms.get(os_name, {}):
                    break

        if platforms:
            result[version] = platforms
            count += 1
            print(f"  ✓ LLVM/Clang {version}")

    return result


# ---------------------------------------------------------------------------
# Build the manifest
# ---------------------------------------------------------------------------

def build_manifest() -> dict:
    """Build the complete manifest."""
    print("=" * 60)
    print("Compendium Registry — Manifest Builder")
    print("=" * 60)
    print()

    manifest = {
        "version": "1",
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "languages": {},
        "tools": {},
    }

    # ── Languages ──────────────────────────────────────────────

    # Go
    go_data = fetch_go()
    if go_data:
        manifest["languages"]["go"] = go_data
    print()

    # Node.js
    node_data = fetch_node()
    if node_data:
        manifest["languages"]["node"] = node_data
    print()

    # Python
    python_data = fetch_python()
    if python_data:
        manifest["languages"]["python"] = python_data
    print()

    # GCC, arm-none-eabi-gcc, riscv-none-elf-gcc (from xPack)
    xpack_data = fetch_all_xpack()
    for tool_name in ["gcc"]:
        if tool_name in xpack_data:
            manifest["languages"][tool_name] = xpack_data[tool_name]
    print()

    # LLVM/Clang
    llvm_data = fetch_llvm()
    if llvm_data:
        manifest["languages"]["clang"] = llvm_data
    print()

    # ── Tools ──────────────────────────────────────────────────

    # xPack tools go to tools section
    for tool_name in ["arm-none-eabi-gcc", "riscv-none-elf-gcc", "make", "openocd"]:
        if tool_name in xpack_data:
            manifest["tools"][tool_name] = xpack_data[tool_name]

    # All other tools
    other_tools = fetch_all_tools()
    manifest["tools"].update(other_tools)
    print()

    # ── Summary ────────────────────────────────────────────────

    lang_count = sum(len(versions) for versions in manifest["languages"].values())
    tool_count = sum(len(versions) for versions in manifest["tools"].values())
    total_tools = len(manifest["languages"]) + len(manifest["tools"])

    print("=" * 60)
    print(f"Manifest built: {total_tools} tools, {lang_count + tool_count} total versions")
    print(f"  Languages: {', '.join(manifest['languages'].keys())}")
    print(f"  Tools:     {', '.join(manifest['tools'].keys())}")
    print("=" * 60)

    return manifest


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    manifest = build_manifest()

    with open(OUTPUT_FILE, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\n✓ Written to {OUTPUT_FILE}")

    # Count FILL_IN checksums
    text = json.dumps(manifest)
    fill_count = text.count("FILL_IN")
    if fill_count > 0:
        print(f"⚠ {fill_count} checksums need to be filled in (marked FILL_IN)")
    else:
        print("✓ All checksums resolved")


if __name__ == "__main__":
    main()
