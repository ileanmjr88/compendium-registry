# Compendium Registry

Public manifest for the Compendium developer environment manager.

Compendium reads this repository to discover which language toolchains and
developer tools are installable, where to download each version, and how to
verify it. The registry is data-first: the JSON files in `languages/` and
`tools/` are the artifact, and the Python scripts exist to keep them current.

## Layout

```
.
├── index.json                  Top-level catalog. Lists every tool with its
│                                latest version, version count, and a pointer
│                                to the per-tool file. Cached aggressively by
│                                clients; kept small on purpose.
├── languages/                  Per-language version maps.
│   ├── aarch64-none-elf-gcc.json    ARMv8-A bare-metal cross compiler (xPack)
│   ├── arm-none-eabi-gcc.json       ARM Cortex-M cross compiler (xPack)
│   ├── clang.json                   LLVM/Clang (upstream)
│   ├── gcc.json                     GCC (xPack)
│   ├── go.json                      Go (go.dev)
│   ├── node.json                    Node.js LTS (nodejs.org)
│   ├── python.json                  CPython via python-build-standalone
│   └── riscv-none-elf-gcc.json      RISC-V cross compiler (xPack)
├── tools/                      Per-tool version maps.
│   ├── bison.json, m4.json, pkg-config.json, realpath.json    xPack utilities
│   ├── ccache.json, cmake.json, ninja.json                    build tooling
│   ├── golangci-lint.json, goreleaser.json, ruff.json,        language tooling
│   │   uv.json, pnpm.json
│   ├── openocd.json                  on-chip debugger (xPack)
│   └── vcpkg.json                    Compendium-repackaged vcpkg
├── scripts/                    All maintenance code. Run from repo root, e.g.
│   │                            `python3 scripts/build_manifest_split.py`.
│   ├── build_manifest_split.py    Fetches upstream releases, merges new
│   │                               versions into the per-tool files,
│   │                               regenerates index.json.
│   ├── fetch_checksums.py         Backfills sha256:FILL_IN placeholders,
│   │                               using companion .sha/.sha256 files when
│   │                               available and stream-and-hash as a fallback.
│   ├── validate_manifest.py       Schema + integrity check. Used by CI and
│   │                               runnable locally before opening a PR.
│   ├── package_tools.py           Builds tarballs for tools that can't be
│   │                               distributed as a single upstream download
│   │                               (currently vcpkg; clang-tools planned).
│   ├── build_all_vcpkg.sh         Driver: package every vcpkg version not
│   │                               already in packages/.
│   └── upload_all_vcpkg.sh        Driver: create one GitHub release per vcpkg
│                                   version and upload its tarballs.
├── .github/workflows/          CI: weekly registry refresh + manifest validation.
├── packages/                   (gitignored) Built tarballs awaiting upload.
└── logs/                       (gitignored) Per-version build logs.
```

## Data model

A per-tool file is a flat map of `version → { os → { arch → artifact } }`:

```jsonc
// tools/ninja.json
{
  "1.13.2": {
    "linux":  { "amd64": { "url": "...", "checksum": "sha256:...", "size": 123, "strip": 0 },
                "arm64": { ... } },
    "darwin": { "amd64": { ... }, "arm64": { ... } }
  },
  "1.13.1": { ... }
}
```

A language entry may include a `depends` map (e.g. `clang` depends on a
specific Python at install time). Versions are never removed once published —
clients pin to specific versions, so deleting one is a breaking change.

`index.json` mirrors the per-tool files but only carries the latest version
and a pointer, so clients can do a cheap "what's new?" check before fetching
the full data:

```jsonc
{
  "version": "2",
  "updated_at": "2026-05-13",
  "languages": {
    "clang": { "latest": "22.1.5", "versions": 24, "file": "languages/clang.json" },
    ...
  },
  "tools": { ... }
}
```

## Data sources

| Tool                    | Source                                                 |
| ----------------------- | ------------------------------------------------------ |
| Go                      | `go.dev/dl/?mode=json&include=all`                     |
| Node.js                 | `nodejs.org/dist/index.json` (LTS only)                |
| Python                  | `astral-sh/python-build-standalone` releases           |
| Clang/LLVM              | `llvm/llvm-project` releases                           |
| GCC, *-none-elf-gcc     | `xpack-dev-tools/*-xpack` releases                     |
| openocd, bison, m4, pkg-config, realpath | `xpack-dev-tools/*-xpack` releases    |
| cmake                   | `Kitware/CMake` releases                               |
| ninja                   | `ninja-build/ninja` releases                           |
| ccache                  | `ccache/ccache` releases                               |
| golangci-lint, ruff, uv | `golangci/`, `astral-sh/` releases                     |
| goreleaser              | `goreleaser/goreleaser` releases                       |
| pnpm                    | `pnpm/pnpm` releases                                   |
| vcpkg                   | `microsoft/vcpkg-tool` binaries + `microsoft/vcpkg` repo, repackaged by `scripts/package_tools.py` |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for local-development commands, the
"adding a tool" walkthrough, and how the scheduled GitHub Actions workflows
keep the registry fresh.

## Acknowledgements

Every binary this registry points at is upstream work — see
[ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md) for the full list of projects we
distribute.

## License

This repository uses a split license:

- **Data** (`index.json`, `languages/*.json`, `tools/*.json`) — [CC0 1.0 Universal](LICENSE.data) (public-domain dedication).
- **Code** (Python scripts, shell helpers, anything else) — [MIT](LICENSE.code).

See [LICENSE](LICENSE) for the full breakdown.
