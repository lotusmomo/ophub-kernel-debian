import importlib
import unittest
import hashlib
import json
import tempfile
import subprocess
from pathlib import Path
from unittest.mock import patch
from ophub_kernel.upstream import select_asset
from tests.test_upstream import asset


class GitHubTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.signing = tempfile.TemporaryDirectory()
        cls.home = Path(cls.signing.name)
        cls.home.chmod(0o700)
        subprocess.run(['gpg', '--homedir', str(cls.home), '--batch', '--pinentry-mode', 'loopback', '--passphrase', '',
                        '--quick-generate-key', 'Publication fixture <fixture@localhost>', 'ed25519', 'sign', '1d'], check=True, capture_output=True)
        listing = subprocess.check_output(['gpg', '--homedir', str(cls.home), '--with-colons', '--list-keys'], text=True)
        cls.fingerprint = next(line.split(':')[9] for line in listing.splitlines() if line.startswith('fpr:'))

    @classmethod
    def tearDownClass(cls):
        cls.signing.cleanup()

    def generation(self, www, revision=1, metadata_only=False):
        from ophub_kernel.flatrepo import build_repository
        if not www.exists():
            stage = www.parent / 'deb-stage/DEBIAN'
            stage.mkdir(parents=True)
            (stage / 'control').write_text('Package: image\nVersion: 1\nArchitecture: arm64\nMaintainer: Test <t@localhost>\nDescription: fixture\n')
            subprocess.run(['dpkg-deb', '--root-owner-group', '--build', str(stage.parent), str(www.parent / 'image_1_arm64.deb')], check=True, capture_output=True)
        build_repository([www.parent / 'image_1_arm64.deb'], www, self.home, self.fingerprint,
                         {'kernel_release': '6.12.112-ophub', 'revision': revision, 'metadata_only': metadata_only})
        return json.loads((www / 'build-manifest.json').read_text())

    def setUp(self):
        try:
            self.p = importlib.import_module("ophub_kernel.github")
        except ModuleNotFoundError:
            self.p = None
        self.assertIsNotNone(self.p, "GitHub update tracking missing")
        self.a = select_asset({"assets": [asset("6.12.112.tar.gz")]})
        self.previous = {"asset": self.a.fingerprint(), "recipe_commit": "commit1", "dtb_sha256": "b" * 64}

    def test_unchanged_inputs_skip(self):
        self.assertFalse(self.p.needs_rebuild(self.a, self.previous, "commit1", "b" * 64))

    def test_same_version_replaced_asset_rebuilds(self):
        new = select_asset({"assets": [asset("6.12.112.tar.gz", digest="c" * 64)]})
        self.assertTrue(self.p.needs_rebuild(new, self.previous, "commit1", "b" * 64))

    def test_recipe_or_dtb_changes_rebuild(self):
        self.assertTrue(self.p.needs_rebuild(self.a, self.previous, "commit2", "b" * 64))
        self.assertTrue(self.p.needs_rebuild(self.a, self.previous, "commit1", "d" * 64))

    def test_first_release_rebuilds(self):
        self.assertTrue(self.p.needs_rebuild(self.a, None, "commit1", "b" * 64))

    def test_publish_packages_first_manifest_last_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            www = Path(directory) / 'wwwroot'
            manifest = self.generation(www)
            fake = FakeClient()
            with patch.object(self.p, "GitHubClient", return_value=fake):
                self.p.publish_release("fixture/repo", www, "fixture-token", manifest)
            apt_events = [name for tag, name in fake.events if tag == "apt-6.12"]
            self.assertEqual(apt_events[0], "image_1_arm64.deb")
            self.assertEqual(apt_events[-1], "build-manifest.json")
            fake.data["apt-6.12"]["image_1_arm64.deb"] = b"immutable old package"
            with patch.object(self.p, "GitHubClient", return_value=fake), self.assertRaises(ValueError):
                self.p.publish_release("fixture/repo", www, "fixture-token", manifest)
            self.assertEqual(fake.data["apt-6.12"]["image_1_arm64.deb"], b"immutable old package")

    def test_failed_metadata_upload_restores_previous_indexes(self):
        with tempfile.TemporaryDirectory() as directory:
            www = Path(directory) / 'wwwroot'
            manifest = self.generation(www)
            fake = FakeClient()
            with patch.object(self.p, "GitHubClient", return_value=fake):
                self.p.publish_release("fixture/repo", www, "fixture-token", manifest)
                before = dict(fake.data['apt-6.12'])
                manifest = self.generation(www, 2)
                fake.fail_once = "InRelease"
                with self.assertRaises(RuntimeError):
                    self.p.publish_release("fixture/repo", www, "fixture-token", manifest)
            self.assertEqual(fake.data['apt-6.12'], before)

    def test_metadata_refresh_preserves_immutable_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            www = Path(directory) / 'wwwroot'
            manifest = self.generation(www)
            original = (www / 'InRelease').read_bytes()
            fake = FakeClient()
            with patch.object(self.p, "GitHubClient", return_value=fake):
                self.p.publish_release("fixture/repo", www, "fixture-token", manifest)
                manifest = self.generation(www, metadata_only=True)
                self.p.publish_release("fixture/repo", www, "fixture-token", manifest)
            self.assertEqual(fake.data["kernel-6.12.112-ophub-m13.1"]["InRelease"], original)
            self.assertEqual(fake.data["apt-6.12"]["InRelease"], (www / 'InRelease').read_bytes())

    def test_same_run_retry_keeps_first_snapshot_with_new_signing_time(self):
        with tempfile.TemporaryDirectory() as directory:
            www = Path(directory) / 'wwwroot'
            manifest = self.generation(www)
            original = (www / 'InRelease').read_bytes()
            fake = FakeClient()
            with patch.object(self.p, "GitHubClient", return_value=fake):
                self.p.publish_release("fixture/repo", www, "fixture-token", manifest)
                manifest = self.generation(www)
                self.p.publish_release("fixture/repo", www, "fixture-token", manifest)
            self.assertEqual(fake.data["kernel-6.12.112-ophub-m13.1"]["InRelease"], original)
            self.assertEqual(fake.data["apt-6.12"]["InRelease"], (www / 'InRelease').read_bytes())

    def test_partial_snapshot_resumes_original_metadata_generation(self):
        with tempfile.TemporaryDirectory() as directory:
            www = Path(directory) / 'wwwroot'
            manifest = self.generation(www)
            original = (www / 'InRelease').read_bytes()
            fake = FakeClient()
            fake.kill_once = ('kernel-6.12.112-ophub-m13.1', 'Packages')
            with patch.object(self.p, 'GitHubClient', return_value=fake):
                with self.assertRaises(SystemExit):
                    self.p.publish_release('fixture/repo', www, 'token', manifest)
                manifest = self.generation(www)
                self.p.publish_release('fixture/repo', www, 'token', manifest)
            self.assertEqual(fake.data['kernel-6.12.112-ophub-m13.1']['InRelease'], original)
            self.assertEqual(fake.data['apt-6.12']['InRelease'], (www / 'InRelease').read_bytes())

    def test_process_termination_recovers_before_next_sync_restore(self):
        from ophub_kernel import cli
        with tempfile.TemporaryDirectory() as directory:
            www = Path(directory) / 'wwwroot'
            manifest = self.generation(www)
            fake = FakeClient()
            with patch.object(self.p, 'GitHubClient', return_value=fake):
                self.p.publish_release('fixture/repo', www, 'token', manifest)
                manifest = self.generation(www, 2)
                fake.kill_once = ('apt-6.12', 'InRelease')
                with self.assertRaises(SystemExit):
                    self.p.publish_release('fixture/repo', www, 'token', manifest)
            self.assertNotIn('InRelease', fake.data['apt-6.12'])
            with patch.object(cli, 'GitHubClient', return_value=fake):
                restored = cli.restore_previous('fixture/repo', Path(directory) / 'restored', self.home, self.fingerprint)
            self.assertEqual(restored['revision'], 2)
            self.assertEqual(fake.data['apt-6.12']['InRelease'], (www / 'InRelease').read_bytes())
            self.assertNotIn('publication-journal.tar.xz', fake.data['apt-6.12'])


class FakeClient:
    """In-memory external GitHub boundary; publishing algorithm stays real."""
    def __init__(self):
        self.data, self.events, self.fail_once, self.kill_once = {}, [], None, None

    def release(self, tag):
        return {'id': tag, 'tag_name': tag} if tag in self.data else None

    def ensure_release(self, tag):
        self.data.setdefault(tag, {})
        return {"id": tag, "tag_name": tag}

    def assets(self, release):
        return {name: {"id": name, "name": name, "release": release["id"],
                       "digest": "sha256:" + hashlib.sha256(data).hexdigest()}
                for name, data in self.data[release["id"]].items()}

    def download(self, asset):
        return self.data[asset["release"]][asset["name"]]

    def delete(self, asset):
        del self.data[asset["release"]][asset["name"]]

    def upload(self, release, name, data):
        if self.kill_once == (release['id'], name):
            self.kill_once = None
            raise SystemExit('fixture publishing process terminated')
        if release["id"] == "apt-6.12" and name == self.fail_once:
            self.fail_once = None
            raise RuntimeError("fixture upload interrupted")
        self.data[release["id"]][name] = data
        self.events.append((release["id"], name))
