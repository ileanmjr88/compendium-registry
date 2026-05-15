# Acknowledgements

This registry is a distribution layer. Every binary it points at is the work
of someone else — full credit goes to the upstream projects below.

## Languages

- [Go](https://go.dev/)
- [Node.js](https://nodejs.org/)
- [LLVM / Clang](https://llvm.org/) — source releases from [`llvm/llvm-project`](https://github.com/llvm/llvm-project)
- [GCC](https://gcc.gnu.org/) — packaged by [xPack](https://xpack.github.io/)
- [CPython](https://www.python.org/) — relocatable builds via [`astral-sh/python-build-standalone`](https://github.com/astral-sh/python-build-standalone)

## Cross-compilers (xPack)

- [arm-none-eabi-gcc](https://github.com/xpack-dev-tools/arm-none-eabi-gcc-xpack) — ARM Cortex-M bare-metal
- [aarch64-none-elf-gcc](https://github.com/xpack-dev-tools/aarch64-none-elf-gcc-xpack) — ARMv8-A bare-metal
- [riscv-none-elf-gcc](https://github.com/xpack-dev-tools/riscv-none-elf-gcc-xpack) — RISC-V bare-metal

## Build systems & developer tools

- [CMake](https://cmake.org/) by [Kitware](https://www.kitware.com/)
- [Ninja](https://ninja-build.org/)
- [ccache](https://ccache.dev/)
- [vcpkg](https://vcpkg.io/) by Microsoft ([`microsoft/vcpkg`](https://github.com/microsoft/vcpkg) + [`microsoft/vcpkg-tool`](https://github.com/microsoft/vcpkg-tool))
- [OpenOCD](https://openocd.org/) — on-chip debugger, packaged by [xPack](https://xpack.github.io/)

## GNU utilities (xPack-packaged)

- [GNU Bison](https://www.gnu.org/software/bison/)
- [GNU M4](https://www.gnu.org/software/m4/)
- [pkg-config](https://www.freedesktop.org/wiki/Software/pkg-config/)
- [realpath](https://www.gnu.org/software/coreutils/) (from GNU coreutils)

## Language tooling

- [uv](https://github.com/astral-sh/uv) and [Ruff](https://github.com/astral-sh/ruff) by [Astral](https://astral.sh/)
- [pnpm](https://pnpm.io/) — fast, disk-efficient Node.js package manager
- [golangci-lint](https://golangci-lint.run/) — fast Go linters runner
- [GoReleaser](https://goreleaser.com/) — release automation for Go projects

## Special thanks

- The [xPack Project](https://xpack.github.io/) for the cross-platform
  reproducible toolchain builds that make a large fraction of `languages/`
  and `tools/` possible — a single upstream that ships consistent
  `{linux,darwin}-{amd64,arm64}` tarballs is the difference between this
  registry being maintainable and not.
