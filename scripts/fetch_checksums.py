#!/usr/bin/env python3
"""Fetch missing checksums for per-tool JSON entries marked sha256:FILL_IN.

Walks index.json, opens each per-tool file under languages/ and tools/,
resolves any sha256:FILL_IN placeholders by:
  1. trying companion .sha256 / .sha256sum files,
  2. trying project-specific checksums files (golangci-lint, pnpm),
  3. trying generic GitHub release checksum files,
  4. otherwise streaming the artifact and computing the hash directly.

Run from repo root after scripts/build_manifest_split.py to backfill checksums
upstream didn't expose.
"""

import hashlib
import json
import os
import re
import sys
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

def fetch_url(url, timeout=30):
    """Fetch URL content as bytes."""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "compendium-checksum-fetcher/0.1")
    if GITHUB_TOKEN and "api.github.com" in url:
        req.add_header("Authorization", f"token {GITHUB_TOKEN}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()

def fetch_text(url):
    """Fetch URL as text, return None on failure."""
    try:
        return fetch_url(url).decode("utf-8")
    except Exception:
        return None

def sha256_from_stream(url, timeout=600):
    """Download URL and compute SHA256 hash by streaming."""
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "compendium-checksum-fetcher/0.1")
    h = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        while True:
            chunk = resp.read(1 << 20)  # 1MB chunks
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

def try_companion_sha256(url):
    """Try fetching {url}.sha256 companion file."""
    # .sha is the xPack convention; .sha256/.sha256sum cover most other projects.
    for suffix in [".sha256", ".sha256sum", ".sha"]:
        text = fetch_text(url + suffix)
        if text:
            # Format: either just hash, or "hash  filename"
            return text.strip().split()[0]
    return None

def try_github_checksums_file(url):
    """For GitHub releases, try to find a checksums file in the same release."""
    # Parse: https://github.com/{owner}/{repo}/releases/download/{tag}/{filename}
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)/releases/download/([^/]+)/(.+)", url)
    if not m:
        return None
    owner, repo, tag, filename = m.groups()

    # Common checksum file names
    checksum_filenames = [
        "SHA256SUMS",
        "sha256sums.txt",
        "checksums.txt",
        f"{filename}.sha256",
    ]

    base_url = f"https://github.com/{owner}/{repo}/releases/download/{tag}"

    for cf in checksum_filenames:
        text = fetch_text(f"{base_url}/{cf}")
        if text:
            for line in text.strip().split("\n"):
                parts = line.strip().split()
                if len(parts) >= 2:
                    hash_val, fname = parts[0], parts[-1]
                    # fname might have leading * or ./
                    fname = fname.lstrip("*").lstrip("./")
                    if fname == filename or fname.endswith("/" + filename):
                        return hash_val
                elif len(parts) == 1 and cf.endswith(".sha256"):
                    # Just the hash
                    return parts[0]
    return None

def try_golangci_lint_checksums(url):
    """golangci-lint publishes a checksums.txt in each release."""
    m = re.match(r"https://github\.com/golangci/golangci-lint/releases/download/(v[^/]+)/(.+)", url)
    if not m:
        return None
    tag, filename = m.groups()
    text = fetch_text(f"https://github.com/golangci/golangci-lint/releases/download/{tag}/golangci-lint-{tag[1:]}-checksums.txt")
    if text:
        for line in text.strip().split("\n"):
            parts = line.strip().split()
            if len(parts) == 2 and parts[1] == filename:
                return parts[0]
    return None

def try_pnpm_checksums(url):
    """pnpm publishes SHASUMS256.txt."""
    m = re.match(r"https://github\.com/pnpm/pnpm/releases/download/(v[^/]+)/(.+)", url)
    if not m:
        return None
    tag, filename = m.groups()
    text = fetch_text(f"https://github.com/pnpm/pnpm/releases/download/{tag}/SHASUMS256.txt")
    if text:
        for line in text.strip().split("\n"):
            parts = line.strip().split()
            if len(parts) >= 2 and filename in parts[-1]:
                return parts[0]
    return None

def get_checksum(url):
    """Try all methods to get a SHA256 checksum for a URL."""
    # 1. Try companion .sha256 file
    h = try_companion_sha256(url)
    if h and len(h) == 64:
        return h, "companion"

    # 2. Try project-specific checksum files
    h = try_golangci_lint_checksums(url)
    if h and len(h) == 64:
        return h, "golangci-checksums"

    h = try_pnpm_checksums(url)
    if h and len(h) == 64:
        return h, "pnpm-checksums"

    # 3. Try generic GitHub checksums file
    h = try_github_checksums_file(url)
    if h and len(h) == 64:
        return h, "github-checksums"

    # 4. Fall back to downloading and computing
    print(f"  Downloading full file: {url.split('/')[-1]}")
    h = sha256_from_stream(url)
    return h, "downloaded"


def collect_fill_ins(manifest, path_keys=None):
    """Walk manifest and collect all (key_path_list, url) pairs where checksum is FILL_IN."""
    if path_keys is None:
        path_keys = []
    results = []
    if isinstance(manifest, dict):
        if manifest.get("checksum") == "sha256:FILL_IN" and "url" in manifest:
            results.append((list(path_keys), manifest["url"]))
        else:
            for k, v in manifest.items():
                results.extend(collect_fill_ins(v, path_keys + [k]))
    elif isinstance(manifest, list):
        for i, v in enumerate(manifest):
            results.extend(collect_fill_ins(v, path_keys + [i]))
    return results

def set_checksum(manifest, key_path, checksum):
    """Set checksum at the given key path."""
    obj = manifest
    for key in key_path:
        obj = obj[key]
    obj["checksum"] = f"sha256:{checksum}"

def main():
    # Load index to discover per-tool files
    with open("index.json") as f:
        index = json.load(f)

    # Collect all per-tool files
    tool_files = []
    for section in ["languages", "tools"]:
        for tool_name, meta in index.get(section, {}).items():
            tool_files.append(meta["file"])

    # Gather all FILL_IN entries across per-tool files
    all_fill_ins = []  # (file_path, key_path, url)
    for tf in tool_files:
        with open(tf) as f:
            data = json.load(f)
        fill_ins = collect_fill_ins(data)
        for path, url in fill_ins:
            all_fill_ins.append((tf, path, url))

    print(f"Found {len(all_fill_ins)} FILL_IN checksums to resolve\n")

    # Deduplicate URLs (some macos amd64/arm64 share the same URL)
    url_to_entries = {}
    for tf, path, url in all_fill_ins:
        url_to_entries.setdefault(url, []).append((tf, path))

    unique_urls = list(url_to_entries.keys())
    print(f"Unique URLs: {len(unique_urls)}\n")

    results = {}

    def process(url):
        try:
            h, method = get_checksum(url)
            return url, h, method, None
        except Exception as e:
            return url, None, None, str(e)

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(process, url): url for url in unique_urls}
        done = 0
        for future in as_completed(futures):
            url, h, method, err = future.result()
            done += 1
            fname = url.split("/")[-1][:60]
            if h:
                print(f"  [{done}/{len(unique_urls)}] {fname} -> {h[:16]}... ({method})")
                results[url] = h
            else:
                print(f"  [{done}/{len(unique_urls)}] FAILED {fname}: {err}")

    # Apply results — group by file, load once, apply all, write once
    applied = 0
    files_to_update = {}
    for url, checksum in results.items():
        for tf, path in url_to_entries[url]:
            files_to_update.setdefault(tf, []).append((path, checksum))

    for tf, updates in files_to_update.items():
        with open(tf) as f:
            data = json.load(f)
        for path, checksum in updates:
            set_checksum(data, path, checksum)
            applied += 1
        with open(tf, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        print(f"  Updated {tf}")

    remaining = len(all_fill_ins) - applied
    print(f"\nApplied {applied} checksums.")
    if remaining > 0:
        print(f"WARNING: {remaining} checksums still missing!")
    else:
        print("All checksums resolved!")

if __name__ == "__main__":
    main()
