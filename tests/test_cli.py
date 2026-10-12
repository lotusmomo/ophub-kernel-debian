import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from tests.test_upstream import asset
from ophub_kernel.upstream import select_asset, sha256_file


class CliTests(unittest.TestCase):
    def test_offline_asset_selection(self):
        self.assertIsNotNone(importlib.util.find_spec("ophub_kernel.cli"), "CLI missing")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "release.json"
            source.write_text(json.dumps({"assets": [asset("6.12.112.tar.gz"), asset("6.12.99.tar.gz")]}))
            result = subprocess.run([sys.executable, "-m", "ophub_kernel.cli", "check-upstream",
                                     "--from-json", str(source)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["version"], "6.12.112")

    def test_publish_requires_explicit_token(self):
        self.assertIsNotNone(importlib.util.find_spec("ophub_kernel.cli"), "CLI missing")
        environment = dict(os.environ)
        environment.pop("GITHUB_TOKEN", None)
        result = subprocess.run([sys.executable, "-m", "ophub_kernel.cli", "publish", "--repo", "fixture/repo",
                                 "--output", "/missing"], env=environment, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("GITHUB_TOKEN", result.stderr)

    def test_cached_build_is_bound_to_recipe_inputs_and_package_bytes(self):
        from ophub_kernel import cli
        self.assertTrue(hasattr(cli, "check_cached_inputs"), "cache integrity check missing")
        selected = select_asset({"assets": [asset("6.12.112.tar.gz")]})
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            deb = output / "fixture.deb"
            deb.write_bytes(b"package")
            manifest = {"asset": selected.fingerprint(), "recipe_commit": "recipe", "dtb_sha256": "dtb",
                        "package_hashes": {deb.name: sha256_file(deb)}}
            cli.check_cached_inputs(output, manifest, selected, "recipe", "dtb")
            for change in ({"recipe_commit": "changed"}, {"dtb_sha256": "changed"}):
                with self.assertRaises(ValueError):
                    cli.check_cached_inputs(output, dict(manifest, **change), selected, "recipe", "dtb")
            deb.write_bytes(b"different")
            with self.assertRaises(ValueError):
                cli.check_cached_inputs(output, manifest, selected, "recipe", "dtb")
