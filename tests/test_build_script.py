import subprocess
import unittest
from pathlib import Path


class BuildScriptTests(unittest.TestCase):
    def test_missing_key_fails_before_building(self):
        script = Path(__file__).resolve().parents[1] / "scripts/build-local.sh"
        self.assertTrue(script.is_file(), "local build entrypoint missing")
        result = subprocess.run(["bash", str(script), "1", "/missing-signing-home", "A" * 40],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("signing", result.stderr.lower())
