#!/usr/bin/env python3
"""Pin official release assets. Python's standard library is sufficient."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
REPO = "earendil-works/pi"
ASSETS = {
    "x86_64-linux": "pi-linux-x64.tar.gz",
    "aarch64-linux": "pi-linux-arm64.tar.gz",
    "x86_64-darwin": "pi-darwin-x64.tar.gz",
    "aarch64-darwin": "pi-darwin-arm64.tar.gz",
}


def download(url):
    headers = {"User-Agent": "pi-coding-agent-nix-updater"}
    # Never leak a GitHub API token to release asset hosts.
    if url.startswith("https://api.github.com/") and os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    return urllib.request.urlopen(
        urllib.request.Request(url, headers=headers), timeout=120
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", help="explicit release, e.g. 1.5.0")
    parser.add_argument("--force", action="store_true", help="reverify the current release")
    args = parser.parse_args()
    if args.version and not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
        parser.error("--version must be a stable X.Y.Z release")
    endpoint = f"tags/v{args.version}" if args.version else "latest"
    with download(f"https://api.github.com/repos/{REPO}/releases/{endpoint}") as response:
        release = json.load(response)
    tag = release["tag_name"]
    if release["draft"] or release["prerelease"] or not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise ValueError(f"Not a stable release: {tag}")
    version = tag[1:]
    target = ROOT / "sources.json"
    current = json.loads(target.read_text()) if target.exists() else {}
    if current.get("version") == version and not args.force:
        print(f"Already up to date: {tag}")
        return
    assets = {asset["name"]: asset["browser_download_url"] for asset in release["assets"]}
    expected_prefix = f"https://github.com/{REPO}/releases/download/{tag}/"
    for name in [*ASSETS.values(), "SHA256SUMS"]:
        if not assets.get(name, "").startswith(expected_prefix):
            raise ValueError(f"Missing or unexpected release asset: {name}")
    with download(assets["SHA256SUMS"]) as response:
        checksums = {}
        for line in response.read().decode().splitlines():
            checksum, name = line.split(maxsplit=1)
            checksums[name.lstrip("*")] = checksum
    updated = {"version": version, "platforms": {}}
    for system, name in ASSETS.items():
        print(f"Verifying {system}: {name}", flush=True)
        digest = hashlib.sha256()
        with download(assets[name]) as response:
            for chunk in iter(lambda: response.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != checksums.get(name):
            raise ValueError(f"SHA256SUMS mismatch for {name}")
        updated["platforms"][system] = {
            "name": name,
            "hash": "sha256-" + base64.b64encode(digest.digest()).decode(),
        }
    # Replace only after every asset verifies. A failed update preserves all pins.
    with tempfile.NamedTemporaryFile("w", dir=ROOT, delete=False) as output:
        temporary = Path(output.name)
        json.dump(updated, output, indent=2)
        output.write("\n")
    try:
        temporary.chmod(0o644)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Pinned {tag}; run nix-build to test before committing.")


if __name__ == "__main__":
    main()
