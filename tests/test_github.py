import importlib
import unittest
import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from ophub_kernel.upstream import select_asset
from tests.test_upstream import asset


class GitHubTests(unittest.TestCase):
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
            www = Path(directory)
            (www / "image_1_arm64.deb").write_bytes(b"package")
            for name in ("Packages", "Release", "InRelease", "build-manifest.json"):
                (www / name).write_bytes(b"new metadata")
            fake = FakeClient()
            manifest = {"kernel_release": "6.12.112-ophub", "revision": 1,
                        "packages": [{"filename": "image_1_arm64.deb", "sha256": hashlib.sha256(b"package").hexdigest()}]}
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
            www = Path(directory)
            for name in ("Packages", "Release", "InRelease", "build-manifest.json"):
                (www / name).write_bytes(b"new")
            fake = FakeClient()
            fake.data["apt-6.12"] = {name: b"old" for name in ("Packages", "Release", "InRelease", "build-manifest.json")}
            fake.fail_once = "InRelease"
            with patch.object(self.p, "GitHubClient", return_value=fake), self.assertRaises(RuntimeError):
                self.p.publish_release("fixture/repo", www, "fixture-token", {"kernel_release": "6.12.112-ophub", "revision": 1, "packages": []})
            self.assertTrue(all(data == b"old" for data in fake.data["apt-6.12"].values()))

    def test_metadata_refresh_preserves_immutable_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            www = Path(directory)
            for name in ("Packages", "Release", "InRelease", "build-manifest.json"):
                (www / name).write_bytes(b"first")
            fake = FakeClient()
            manifest = {"kernel_release": "6.12.112-ophub", "revision": 1, "packages": []}
            with patch.object(self.p, "GitHubClient", return_value=fake):
                self.p.publish_release("fixture/repo", www, "fixture-token", manifest)
                (www / "InRelease").write_bytes(b"renewed")
                self.p.publish_release("fixture/repo", www, "fixture-token", dict(manifest, metadata_only=True))
            self.assertEqual(fake.data["kernel-6.12.112-ophub-m13.1"]["InRelease"], b"first")
            self.assertEqual(fake.data["apt-6.12"]["InRelease"], b"renewed")

    def test_same_run_retry_keeps_first_snapshot_with_new_signing_time(self):
        with tempfile.TemporaryDirectory() as directory:
            www = Path(directory)
            manifest = {"kernel_release": "6.12.112-ophub", "revision": 1, "packages": [], "metadata_generated_at": "first"}
            for name in ("Packages", "Release", "InRelease"):
                (www / name).write_bytes(b"first")
            (www / "build-manifest.json").write_text(json.dumps(manifest))
            fake = FakeClient()
            with patch.object(self.p, "GitHubClient", return_value=fake):
                self.p.publish_release("fixture/repo", www, "fixture-token", manifest)
                manifest["metadata_generated_at"] = "retry"
                (www / "build-manifest.json").write_text(json.dumps(manifest))
                (www / "InRelease").write_bytes(b"retry signature")
                self.p.publish_release("fixture/repo", www, "fixture-token", manifest)
            self.assertEqual(fake.data["kernel-6.12.112-ophub-m13.1"]["InRelease"], b"first")
            self.assertEqual(fake.data["apt-6.12"]["InRelease"], b"retry signature")


class FakeClient:
    """In-memory external GitHub boundary; publishing algorithm stays real."""
    def __init__(self):
        self.data, self.events, self.fail_once = {}, [], None

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
        if release["id"] == "apt-6.12" and name == self.fail_once:
            self.fail_once = None
            raise RuntimeError("fixture upload interrupted")
        self.data[release["id"]][name] = data
        self.events.append((release["id"], name))
