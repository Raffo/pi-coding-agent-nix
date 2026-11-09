# pi-coding-agent-nix

Classic, non-flake Nix packaging of the official **Pi coding agent standalone
release**, following [Raffo/github-copilot-cli-nix](https://github.com/Raffo/github-copilot-cli-nix).
No experimental features, npm install, or network access during the package build.

## Build and run

```sh
nix-build
./result/bin/pi --version
./result/bin/pi
```

Optional profile installation:

```sh
nix-env -if .
```

The default build uses the exact Nixpkgs revision and unpacked hash in
`nixpkgs.json`, rather than your current channel. To use your own Nixpkgs:

```sh
nix-build --arg pkgs 'import <nixpkgs> {}'
```

Pi still needs your model-provider credentials to make requests. No credentials
are needed to build or run the included checks.

## Overlay

```nix
{
  nixpkgs.overlays = [ (import /path/to/pi-coding-agent-nix/overlay.nix) ];
  environment.systemPackages = [ pkgs.pi-coding-agent ];
}
```

The overlay uses **your** Nixpkgs, not this repository's pin. You can also use
the conventional `pkgs.callPackage /path/to/package.nix { }`.

## Update

Python 3 is the only updater dependency:

```sh
./update.sh                    # latest stable release
./update.sh --version 1.5.0     # specific stable release
./update.sh --force            # re-download and verify current release
nix-build                     # test before committing
git diff -- sources.json
```

The updater tracks `earendil-works/pi`, not the obsolete
`@mariozechner/pi-coding-agent` npm package name. It downloads all four archives,
computes their SHA-256 hashes, verifies upstream `SHA256SUMS`, and atomically
replaces `sources.json` only when everything verifies.

Release checksums are **not independent signatures**. This trusts upstream
GitHub releases; review changes before accepting new pins. The build itself uses
the committed hashes, not mutable release metadata.

After you push this repository to GitHub, an included workflow checks every six
hours, builds/tests x86_64-linux, then opens an update PR. It does not auto-merge.
Enable Actions' **Allow GitHub Actions to create and approve pull requests**
repository setting. No remote has been created or configured on this VM.

## Development and tests

```sh
nix-shell
python3 -m unittest discover -s tests -v
shellcheck update.sh
nixfmt --check *.nix
nix-build --option experimental-features ''
```

Build-time checks cover `--version`, `--help`, bundled theme/export assets,
offline HTML session export, and loading the shipped native clipboard helpers.
Updater tests are offline and verify failure does not overwrite good pins.

To refresh the stable Nixpkgs pin deliberately:

```sh
rev=$(curl -fsSL https://channels.nixos.org/nixos-26.05/git-revision)
hash=$(nix-prefetch-url --unpack "https://github.com/NixOS/nixpkgs/archive/$rev.tar.gz")
python3 - "$rev" "$hash" <<'PY'
import json, sys
with open("nixpkgs.json", "w") as f:
    json.dump(dict(rev=sys.argv[1], sha256=sys.argv[2]), f, indent=2)
    f.write("\n")
PY
nix-build
```

## Packaging details and scope

- Pins **1.5.0**, released November 2, 2026.
- As checked November 7, 2026, Nixpkgs **master already has 1.5.0**;
  the **nixos-26.05** branch still has 0.75.4. This repository is an independent
  stable-channel override, not an unsubmitted version bump for master.
- This **repackages upstream binaries**, just like the reference repository.
  It does not compile Pi from source. For source-oriented Nixpkgs work, start
  from upstream's separately callable
  [`nix/package.nix`](https://github.com/earendil-works/pi/blob/v1.5.0/nix/package.nix)
  or the current Nixpkgs source derivation; neither requires using a flake.
- Installs the whole archive under `$out/lib/pi`, including themes, HTML
  templates, WASM, examples, and native helpers. `PI_PACKAGE_DIR` points there.
- Linux ELF interpreter/RPATH and the libxcb-dependent helper are patched for
  Nix. On ARM64, only the main executable's interpreter is patched: adding an
  RPATH corrupts its ELF version metadata and crashes the loader. Its glibc
  dependencies resolve through the Nix interpreter without an RPATH or
  `LD_LIBRARY_PATH`. On x86_64, keep its RPATH limited to glibc: adding an
  unnecessary long GCC RPATH made this Bun executable segfault with patchelf
  0.15.2 during validation.
- Supplies bash, fd, ripgrep, CA certificates, and Linux clipboard commands.
  Node/npm are appended to PATH for package management without overriding your
  preferred Node installation. The core executable embeds its own Bun runtime.
- Disables version-check notices and telemetry by default; callers can override
  the corresponding environment variables. Update through Nix, not `pi update self`.
- Assets are pinned for x86_64/aarch64 Linux and macOS. **Both x86_64-linux and
  aarch64-linux have been built and runtime-tested natively.** macOS still needs
  native testing; cross-compilation is not claimed.

## This VM

Official stable Nix 2.35.4 is installed with the multi-user daemon, enabled through
systemd. The user's `nixpkgs` channel tracks `nixos-26.05`. Sandbox builds are
enabled; one build runs at a time with two build cores, suitable for this VM's
4 GiB RAM. No experimental features are configured.

New login shells load Nix automatically. For a shell opened before installation:

```sh
. /etc/profile.d/nix.sh
```

Your existing `pi` command was left untouched. Run this build explicitly through
`./result/bin/pi`, or use the optional profile installation above and check
`command -v pi` for PATH precedence.
