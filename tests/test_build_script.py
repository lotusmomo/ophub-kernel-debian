import subprocess
import os
import re
import unittest
from pathlib import Path


class BuildScriptTests(unittest.TestCase):
    def test_workflow_revision_is_newer_than_existing_local_packages(self):
        workflow = Path(__file__).resolve().parents[1] / ".github/workflows/sync-kernel.yml"
        expression = re.search(r'--revision "(\$\(\([^"]+\)\))"', workflow.read_text()).group(1)
        value = subprocess.check_output(["bash", "-c", 'printf "%s" "' + expression + '"'],
                                        env=dict(os.environ, GITHUB_RUN_NUMBER="1"), text=True)
        self.assertEqual(value, "1001")
        subprocess.run(["dpkg", "--compare-versions", "1:6.12.112-1+ophub." + value,
                        "gt", "1:6.12.112-1+m13.2"], check=True)

    def test_missing_key_fails_before_building(self):
        script = Path(__file__).resolve().parents[1] / "scripts/build-local.sh"
        self.assertTrue(script.is_file(), "local build entrypoint missing")
        result = subprocess.run(["bash", str(script), "1", "/missing-signing-home", "A" * 40],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("signing", result.stderr.lower())
