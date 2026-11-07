"""Offline tests for the release-pin updater (stdlib only).

Run with: python3 -m unittest discover -s tests -v
"""

import base64
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import call, patch


SPEC = importlib.util.spec_from_file_location(
    "pi_update", Path(__file__).resolve().parents[1] / "scripts" / "update.py"
)
update = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(update)


class UpdateTests(unittest.TestCase):
    VERSION = "9.8.7"
    ASSETS = {
        "x86_64-linux": "pi-linux-x64.tar.gz",
        "aarch64-linux": "pi-linux-arm64.tar.gz",
        "x86_64-darwin": "pi-darwin-x64.tar.gz",
        "aarch64-darwin": "pi-darwin-arm64.tar.gz",
    }

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.target = self.root / "sources.json"
        self.original = b'{\n  "version": "0.0.1", "platforms": {"old": "pin"}\n}\n'
        self.target.write_bytes(self.original)
        self.prefix = (
            f"https://github.com/{update.REPO}/releases/download/v{self.VERSION}/"
        )
        self.api = f"https://api.github.com/repos/{update.REPO}/releases/"
        self.payloads = {
            name: f"distinct archive contents for {system}\n".encode()
            for system, name in self.ASSETS.items()
        }
        self.release = {
            "tag_name": f"v{self.VERSION}",
            "draft": False,
            "prerelease": False,
            "assets": [
                {"name": name, "browser_download_url": self.prefix + name}
                for name in [*self.ASSETS.values(), "SHA256SUMS"]
            ],
        }
        self.checksums = {
            name: hashlib.sha256(payload).hexdigest()
            for name, payload in self.payloads.items()
        }
        self.addCleanup(patch.stopall)
        patch.object(update, "ROOT", self.root).start()
        # Even an accidental bypass of the fake download must never use the network.
        patch.object(
            update.urllib.request,
            "urlopen",
            side_effect=AssertionError("Network access is forbidden in updater tests"),
        ).start()
        self.download = patch.object(
            update, "download", side_effect=self.fake_download
        ).start()
        patch("sys.stdout", new_callable=io.StringIO).start()
        patch("sys.stderr", new_callable=io.StringIO).start()

    def fake_download(self, url):
        if url in (self.api + "latest", self.api + f"tags/v{self.VERSION}"):
            return io.BytesIO(json.dumps(self.release).encode())
        if url == self.prefix + "SHA256SUMS":
            # Exercise both common checksum manifest formats.
            lines = [
                f"{digest}  {'*' if index % 2 else ''}{name}\n"
                for index, (name, digest) in enumerate(self.checksums.items())
            ]
            return io.BytesIO("".join(lines).encode())
        if url.startswith(self.prefix):
            name = url[len(self.prefix):]
            if name in self.payloads:
                return io.BytesIO(self.payloads[name])
        self.fail(f"Unexpected download: {url}")

    def run_update(self, *arguments):
        with patch("sys.argv", ["update.py", *arguments]):
            update.main()

    def assert_correct_pins(self):
        result = json.loads(self.target.read_text())
        self.assertEqual(result["version"], self.VERSION)
        self.assertEqual(set(result["platforms"]), set(self.ASSETS))
        for system, name in self.ASSETS.items():
            expected_hash = "sha256-" + base64.b64encode(
                hashlib.sha256(self.payloads[name]).digest()
            ).decode()
            self.assertEqual(
                result["platforms"][system], {"name": name, "hash": expected_hash}
            )
        self.assertEqual(list(self.root.iterdir()), [self.target])

    def test_latest_happy_path_writes_all_four_correct_hashes(self):
        self.run_update()

        self.assert_correct_pins()
        self.assertEqual(
            self.download.call_args_list,
            [call(self.api + "latest"), call(self.prefix + "SHA256SUMS")]
            + [call(self.prefix + name) for name in self.ASSETS.values()],
        )

    def test_explicit_version_uses_tag_endpoint(self):
        self.run_update("--version", self.VERSION)

        self.assert_correct_pins()
        self.assertEqual(
            self.download.call_args_list[0],
            call(self.api + f"tags/v{self.VERSION}"),
        )

    def test_checksum_mismatch_preserves_existing_sources_for_every_platform(self):
        for name in self.ASSETS.values():
            with self.subTest(asset=name):
                original_digest = self.checksums[name]
                self.checksums[name] = "0" * 64
                try:
                    with self.assertRaisesRegex(ValueError, "SHA256SUMS mismatch"):
                        self.run_update()
                    self.assertEqual(self.target.read_bytes(), self.original)
                    self.assertEqual(list(self.root.iterdir()), [self.target])
                finally:
                    self.checksums[name] = original_digest

    def test_missing_checksum_preserves_existing_sources(self):
        del self.checksums[list(self.ASSETS.values())[-1]]

        with self.assertRaisesRegex(ValueError, "SHA256SUMS mismatch"):
            self.run_update()

        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertEqual(list(self.root.iterdir()), [self.target])

    def test_current_version_skips_checksum_and_archive_downloads(self):
        current = b'{"version": "9.8.7", "platforms": {"unchanged": "pin"}}\n'
        self.target.write_bytes(current)
        self.release["assets"] = []

        self.run_update()

        self.download.assert_called_once_with(self.api + "latest")
        self.assertEqual(self.target.read_bytes(), current)

    def test_force_reverifies_current_version(self):
        self.target.write_text(json.dumps({"version": self.VERSION}))

        self.run_update("--force")

        self.assert_correct_pins()
        self.assertEqual(self.download.call_count, 6)

    def test_unstable_release_metadata_is_rejected_without_asset_downloads(self):
        stable = copy.deepcopy(self.release)
        for changes in (
            {"prerelease": True},
            {"draft": True},
            {"tag_name": f"v{self.VERSION}-rc.1"},
            {"tag_name": self.VERSION},
        ):
            with self.subTest(changes=changes):
                self.release = {**stable, **changes}
                self.download.reset_mock()
                with self.assertRaisesRegex(ValueError, "Not a stable release"):
                    self.run_update()
                self.download.assert_called_once_with(self.api + "latest")
                self.assertEqual(self.target.read_bytes(), self.original)

    def test_prerelease_version_argument_is_rejected_before_download(self):
        with self.assertRaises(SystemExit) as raised:
            self.run_update("--version", f"{self.VERSION}-rc.1")

        self.assertEqual(raised.exception.code, 2)
        self.download.assert_not_called()
        self.assertEqual(self.target.read_bytes(), self.original)


if __name__ == "__main__":
    unittest.main()
