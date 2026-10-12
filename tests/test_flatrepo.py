import importlib
import json
import getpass
import subprocess
import tempfile
import unittest
from pathlib import Path


class FlatRepoTests(unittest.TestCase):
    def setUp(self):
        try:
            self.p = importlib.import_module("ophub_kernel.flatrepo")
        except ModuleNotFoundError:
            self.p = None
        self.assertIsNotNone(self.p, "flat repository implementation missing")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def fixture_key(self):
        home = self.root / "signing"
        home.mkdir(mode=0o700)
        subprocess.run(["gpg", "--homedir", str(home), "--batch", "--pinentry-mode", "loopback",
            "--passphrase", "", "--quick-generate-key", "Fixture <fixture@localhost>",
            "ed25519", "sign", "1d"], check=True, capture_output=True)
        listing = subprocess.check_output(["gpg", "--homedir", str(home), "--with-colons", "--list-keys"], text=True)
        return home, next(line.split(":")[9] for line in listing.splitlines() if line.startswith("fpr:"))

    def fixture_deb(self, name):
        stage = self.root / (name + "-stage/DEBIAN")
        stage.mkdir(parents=True)
        (stage / "control").write_text(f"Package: {name}\nVersion: 1\nArchitecture: all\nMaintainer: Fixture <fixture@localhost>\nDescription: test\n")
        output = self.root / (name + "_1_all.deb")
        subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(stage.parent), str(output)], check=True, capture_output=True)
        return output

    def test_historical_deb_tamper_cannot_be_resigned(self):
        home, fingerprint = self.fixture_key()
        old = self.fixture_deb("old")
        new = self.fixture_deb("new")
        www = self.p.build_repository([old], self.root / "wwwroot", home, fingerprint, {})
        original_metadata = (www / "InRelease").read_bytes()
        control = self.root / "old-stage/DEBIAN/control"
        control.write_text(control.read_text().replace("Description: test", "Description: changed historical package"))
        subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(control.parent.parent), str(www / old.name)], check=True, capture_output=True)
        with self.assertRaises(ValueError):
            self.p.build_repository([new], www, home, fingerprint, {})
        self.assertEqual((www / "InRelease").read_bytes(), original_metadata)
        self.assertFalse((www / new.name).exists())

    def test_signing_failure_preserves_previous_generation(self):
        home, fingerprint = self.fixture_key()
        old = self.fixture_deb("old")
        new = self.fixture_deb("new")
        www = self.p.build_repository([old], self.root / "wwwroot", home, fingerprint, {})
        before = {p.name: p.read_bytes() for p in www.iterdir()}
        with self.assertRaises((ValueError, subprocess.CalledProcessError)):
            self.p.build_repository([new], www, home, "A" * 40, {})
        self.assertEqual(before, {p.name: p.read_bytes() for p in www.iterdir()})

    def test_missing_signing_home_fails_before_publishing(self):
        with self.assertRaises(ValueError):
            self.p.build_repository([], self.root / "wwwroot", self.root / "missing", "A" * 40, {})
        self.assertFalse((self.root / "wwwroot/InRelease").exists())

    def test_signing_directory_cannot_be_exported(self):
        www = self.root / "wwwroot"
        home = www / "secret"
        home.mkdir(parents=True, mode=0o700)
        with self.assertRaises(ValueError):
            self.p.build_repository([], www, home, "A" * 40, {})

    def test_real_signature_indexes_and_hashes(self):
        home = self.root / "signing"
        home.mkdir(mode=0o700)
        subprocess.run(["gpg", "--homedir", str(home), "--batch", "--pinentry-mode", "loopback",
            "--passphrase", "", "--quick-generate-key", "Fixture <fixture@localhost>",
            "ed25519", "sign", "1d"], check=True, capture_output=True)
        listing = subprocess.check_output(["gpg", "--homedir", str(home), "--with-colons", "--list-keys"], text=True)
        fingerprint = next(line.split(":")[9] for line in listing.splitlines() if line.startswith("fpr:"))
        stage = self.root / "deb/DEBIAN"
        stage.mkdir(parents=True)
        (stage / "control").write_text("Package: fixture\nVersion: 1\nArchitecture: all\n"
            "Maintainer: Fixture <fixture@localhost>\nDescription: test\n")
        deb = self.root / "fixture_1_all.deb"
        subprocess.run(["dpkg-deb", "--root-owner-group", "--build", str(stage.parent), str(deb)],
                       check=True, capture_output=True)
        www = self.p.build_repository([deb], self.root / "wwwroot", home, fingerprint, {"fixture": True})
        result = subprocess.run(["gpgv", "--keyring", str(www / "archive-keyring.gpg"),
                                 str(www / "InRelease")], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        packages = (www / "Packages").read_text()
        self.assertIn("Filename: fixture_1_all.deb", packages)
        self.assertIn("Architecture: all", packages)
        self.assertTrue((www / "Packages.xz").is_file())
        self.assertIn("Valid-Until:", (www / "Release").read_text())
        self.assertNotIn("private", " ".join(path.name for path in www.iterdir()))
        self.assertEqual(json.loads((www / "build-manifest.json").read_text())["fixture"], True)
        import hashlib
        self.assertIn(hashlib.sha256((www / "build-manifest.json").read_bytes()).hexdigest(),
                      (www / "Release").read_text())
        from ophub_kernel import deployment
        self.assertTrue(hasattr(deployment, "verified_manifest"), "authenticated deployment manifest missing")
        self.assertTrue(deployment.verified_manifest(www, www / "archive-keyring.gpg", fingerprint)["fixture"])
        compressed = (www / 'Packages.xz').read_bytes()
        (www / 'Packages.xz').write_bytes(b'corrupted compressed index')
        with self.assertRaises(ValueError):
            deployment.verified_manifest(www, www / 'archive-keyring.gpg', fingerprint, check_packages=False)
        (www / 'Packages.xz').write_bytes(compressed)
        manifest_text = (www / "build-manifest.json").read_text()
        (www / "build-manifest.json").write_text(manifest_text.replace('"fixture": true', '"fixture": false'))
        with self.assertRaises(ValueError):
            deployment.verified_manifest(www, www / "archive-keyring.gpg", fingerprint)
        (www / "build-manifest.json").write_text(manifest_text)
        apt = self.root / "apt"
        for directory in ("state/lists/partial", "cache/archives/partial", "etc"):
            (apt / directory).mkdir(parents=True, exist_ok=True)
        (apt / "state/status").write_text("")
        source = apt / "etc/fixture.sources"
        source.write_text("Types: deb\nURIs: " + www.as_uri() + "/\nSuites: ./\nArchitectures: arm64\n"
                          "Signed-By: " + str(www / "archive-keyring.gpg") + "\n")
        command = ["apt-get", "-o", "Dir::State=" + str(apt / "state"),
            "-o", "Dir::State::status=" + str(apt / "state/status"),
            "-o", "Dir::Cache=" + str(apt / "cache"), "-o", "Dir::Etc::sourcelist=" + str(source),
            "-o", "Dir::Etc::sourceparts=-", "-o", "APT::Architecture=arm64",
            "-o", "APT::Sandbox::User=" + getpass.getuser(), "update", "--error-on=any"]
        good = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
        original = (www / "InRelease").read_text()
        (www / "InRelease").write_text(original.replace("Origin: M13", "Origin: Bad"))
        self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
        (www / "InRelease").write_text(original)
