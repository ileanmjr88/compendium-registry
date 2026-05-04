#!/usr/bin/env python3
"""
Compendium Registry — Tool Packaging Script

Assembles tools that can't be distributed as a simple download.
All platforms are built from ONE machine — this is assembly, not compilation.

Currently supported:
  - vcpkg: binary + scripts + triplets + .vcpkg-root + no-op bootstrap

Future:
  - clang-tools: extract clang-tidy + clang-format from full LLVM tarball

Usage:
    python3 package_tools.py vcpkg 2026-02-21
    python3 package_tools.py vcpkg 2026-02-21 --output-dir ./packages
    python3 package_tools.py clang-tools 22.1.2     # future

Run from the compendium-registry repo root. Outputs tarballs + checksums
ready to upload as GitHub Release assets.
"""

import argparse
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

VCPKG_BINARY_URLS = {
    "linux-amd64": "https://github.com/microsoft/vcpkg-tool/releases/download/{version}/vcpkg-glibc",
    "linux-arm64": "https://github.com/microsoft/vcpkg-tool/releases/download/{version}/vcpkg-glibc-arm64",
    "darwin-amd64": "https://github.com/microsoft/vcpkg-tool/releases/download/{version}/vcpkg-macos",
    "darwin-arm64": "https://github.com/microsoft/vcpkg-tool/releases/download/{version}/vcpkg-macos",
}

def vcpkg_repo_tag(version: str) -> str:
    """Find the latest vcpkg repo tag that is <= the tool release date.

    vcpkg-tool uses "2026-04-08", vcpkg repo uses "2026.03.18" — they
    don't release in lockstep, so we pick the nearest repo tag at or before
    the tool release date.
    """
    import json
    req = urllib.request.Request("https://api.github.com/repos/microsoft/vcpkg/tags?per_page=20")
    req.add_header("User-Agent", "compendium-package-tools/0.1")
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        req.add_header("Authorization", f"token {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        tags = json.loads(resp.read().decode("utf-8"))

    # Tags are like "2026.03.18" — convert tool version "2026-04-08" for comparison
    tool_date = version.replace("-", ".")
    for tag in tags:
        name = tag["name"]
        if name <= tool_date:
            return name

    # Fallback: try direct conversion
    return tool_date


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def download(url: str, dest: Path, retries: int = 3):
    """Download a file from a URL with retries."""
    import time
    print(f"    ↓ {url}")
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "compendium-package-tools/0.1")
            with urllib.request.urlopen(req, timeout=120) as resp:
                with open(dest, "wb") as f:
                    shutil.copyfileobj(resp, f)
            print(f"    ✓ saved to {dest.name}")
            return
        except urllib.request.HTTPError as e:
            if attempt < retries and e.code in (502, 503, 429):
                wait = 2 ** attempt
                print(f"    ⚠ HTTP {e.code}, retrying in {wait}s (attempt {attempt}/{retries})")
                time.sleep(wait)
            else:
                raise


def sha256_file(path: Path) -> str:
    """Compute SHA256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def make_executable(path: Path):
    """chmod +x a file."""
    st = os.stat(path)
    os.chmod(path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


# ---------------------------------------------------------------------------
# vcpkg packaging
# ---------------------------------------------------------------------------

def package_vcpkg(version: str, output_dir: Path):
    """
    Package vcpkg for all platforms from one machine.

    Steps:
    1. Clone microsoft/vcpkg at matching tag (one clone, reused for all platforms)
    2. Download pre-built binary for each platform
    3. Drop binary in, add .vcpkg-root, add no-op bootstrap-vcpkg.sh
    4. Remove .git to save space
    5. Tar it up per platform
    6. Compute checksums
    """
    print(f"\n{'='*60}")
    print(f"Packaging vcpkg {version}")
    print(f"{'='*60}\n")

    repo_tag = vcpkg_repo_tag(version)
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # 1. Clone vcpkg repo
        print(f"  → cloning microsoft/vcpkg at tag {repo_tag}")
        vcpkg_src = tmp / "vcpkg-src"
        result = subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", repo_tag,
             "https://github.com/microsoft/vcpkg.git", str(vcpkg_src)],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"  ✗ git clone failed: {result.stderr}")
            sys.exit(1)
        print(f"  ✓ cloned")

        # Remove .git to save space
        shutil.rmtree(vcpkg_src / ".git", ignore_errors=True)

        # 2. Download all platform binaries
        print(f"\n  → downloading pre-built binaries")
        binaries = {}
        for platform_arch, url_template in VCPKG_BINARY_URLS.items():
            url = url_template.format(version=version)
            binary_path = tmp / f"vcpkg-{platform_arch}"
            download(url, binary_path)
            make_executable(binary_path)
            binaries[platform_arch] = binary_path

        # 3. Package for each platform
        print(f"\n  → creating tarballs")
        checksums = {}

        for platform_arch, binary_path in binaries.items():
            print(f"\n  --- {platform_arch} ---")

            # Create a fresh copy of the repo for this platform
            vcpkg_dir = tmp / f"vcpkg-{platform_arch}-pkg" / "vcpkg"
            if vcpkg_dir.exists():
                shutil.rmtree(vcpkg_dir)
            shutil.copytree(vcpkg_src, vcpkg_dir)

            # Drop in the pre-built binary
            dest_binary = vcpkg_dir / "vcpkg"
            shutil.copy2(binary_path, dest_binary)
            make_executable(dest_binary)
            print(f"    ✓ binary copied")

            # Add .vcpkg-root marker file
            (vcpkg_dir / ".vcpkg-root").touch()
            print(f"    ✓ .vcpkg-root created")

            # Replace bootstrap-vcpkg.sh with no-op
            bootstrap_sh = vcpkg_dir / "bootstrap-vcpkg.sh"
            bootstrap_sh.write_text(
                '#!/bin/sh\n'
                'echo "vcpkg binary provided by Compendium — skipping bootstrap"\n'
            )
            make_executable(bootstrap_sh)
            print(f"    ✓ bootstrap-vcpkg.sh replaced with no-op")

            # Replace bootstrap-vcpkg.bat with no-op (for completeness)
            bootstrap_bat = vcpkg_dir / "bootstrap-vcpkg.bat"
            if bootstrap_bat.exists():
                bootstrap_bat.write_text(
                    '@echo off\n'
                    'echo vcpkg binary provided by Compendium - skipping bootstrap\n'
                )
                print(f"    ✓ bootstrap-vcpkg.bat replaced with no-op")

            # Tar it up
            tarball_name = f"vcpkg-{version}-{platform_arch}.tar.gz"
            tarball_path = output_dir / tarball_name

            # Create tarball from parent directory so it extracts as vcpkg/
            parent_dir = vcpkg_dir.parent
            subprocess.run(
                ["tar", "czf", str(tarball_path), "-C", str(parent_dir), "vcpkg"],
                check=True
            )

            checksum = sha256_file(tarball_path)
            checksums[platform_arch] = {
                "file": tarball_name,
                "checksum": checksum,
                "size": tarball_path.stat().st_size,
            }

            size_mb = tarball_path.stat().st_size / (1024 * 1024)
            print(f"    ✓ {tarball_name} ({size_mb:.1f} MB)")
            print(f"    ✓ sha256:{checksum}")

    # 4. Write checksums file
    checksums_path = output_dir / f"vcpkg-{version}-checksums.txt"
    with open(checksums_path, "w") as f:
        for platform_arch, info in sorted(checksums.items()):
            f.write(f"sha256:{info['checksum']}  {info['file']}\n")
    print(f"\n  ✓ checksums written to {checksums_path.name}")

    # 5. Print manifest snippet
    print(f"\n{'='*60}")
    print(f"Manifest snippet for vcpkg {version}")
    print(f"{'='*60}\n")

    # Assume uploads go to compendium-registry releases
    base_url = f"https://github.com/ileanmjr88/compendium-registry/releases/download/v0.1.0"

    for platform_arch, info in sorted(checksums.items()):
        os_name, arch = platform_arch.split("-")
        print(f'  "{os_name}": {{')
        print(f'    "{arch}": {{')
        print(f'      "url": "{base_url}/{info["file"]}",')
        print(f'      "checksum": "sha256:{info["checksum"]}",')
        print(f'      "size": {info["size"]},')
        print(f'      "strip": 1')
        print(f'    }}')
        print(f'  }}')

    print(f"\n✓ Done. Upload tarballs from {output_dir}/ as GitHub Release assets.")
    print(f"  Then update manifest.json (or tools/vcpkg.json) with the URLs and checksums above.")


# ---------------------------------------------------------------------------
# clang-tools packaging (future)
# ---------------------------------------------------------------------------

def package_clang_tools(version: str, output_dir: Path):
    """
    Extract clang-tidy + clang-format from full LLVM tarball.
    Creates a slim package with just the analysis tools.

    Future implementation:
    1. Download full LLVM tarball for each platform
    2. Extract only bin/clang-tidy, bin/clang-format, bin/clang-apply-replacements
    3. Include necessary shared libraries (if any)
    4. Tar up the slim package
    5. Compute checksums
    """
    print(f"\n{'='*60}")
    print(f"Packaging clang-tools {version}")
    print(f"{'='*60}\n")
    print("  ✗ Not yet implemented. Coming in v0.2.")
    print()
    print("  Plan:")
    print("    1. Download full LLVM tarball per platform (~1.5GB each)")
    print("    2. Extract only: bin/clang-tidy, bin/clang-format, bin/clang-apply-replacements")
    print("    3. Include required shared libs from lib/")
    print("    4. Package as clang-tools-{version}-{os}-{arch}.tar.gz (~50MB each)")
    print("    5. Upload as registry release asset")
    print()
    print("  This avoids users downloading 1.5GB just for clang-tidy.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Package tools for the Compendium registry"
    )
    parser.add_argument(
        "tool",
        choices=["vcpkg", "clang-tools"],
        help="Tool to package"
    )
    parser.add_argument(
        "version",
        help="Version to package (e.g., 2026-02-21 for vcpkg, 22.1.2 for clang-tools)"
    )
    parser.add_argument(
        "--output-dir",
        default="./packages",
        help="Output directory for tarballs (default: ./packages)"
    )

    args = parser.parse_args()
    output_dir = Path(args.output_dir)

    if args.tool == "vcpkg":
        package_vcpkg(args.version, output_dir)
    elif args.tool == "clang-tools":
        package_clang_tools(args.version, output_dir)


if __name__ == "__main__":
    main()
