import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from tests.test_upstream import asset


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
