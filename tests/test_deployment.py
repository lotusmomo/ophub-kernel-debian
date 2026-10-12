import importlib
import unittest
import tempfile
from pathlib import Path


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        try:
            self.p = importlib.import_module("ophub_kernel.deployment")
        except ModuleNotFoundError:
            self.p = None
        self.assertIsNotNone(self.p, "configuration rendering missing")

    def test_deb822_flat_source(self):
        fields = dict(line.split(": ", 1) for line in self.p.render_sources(
            "file:/mnt/ophub-kernel/", "/etc/apt/keyrings/ophub-kernel.gpg").splitlines())
        self.assertEqual(fields, {"Types": "deb", "URIs": "file:/mnt/ophub-kernel/", "Suites": "./",
            "Architectures": "arm64", "Signed-By": "/etc/apt/keyrings/ophub-kernel.gpg", "Enabled": "yes"})

    def test_invalid_source_and_keyring_rejected(self):
        for uri in ["nfs://nas/repo", "file:/mnt/x/\nTrusted: yes", "http://insecure.invalid/repo"]:
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                self.p.render_sources(uri, "/etc/apt/keyrings/a.gpg")

    def test_export_limits_access(self):
        text = self.p.render_export(Path("/srv/wwwroot"), "192.0.2.20")
        self.assertEqual(text, "/srv/wwwroot 192.0.2.20(ro,sync,no_subtree_check,root_squash)\n")
        with self.assertRaises(ValueError):
            self.p.render_export(Path("/srv/private dir"), "192.0.2.20")

    def test_ntp_uses_requested_server_and_resets_lists(self):
        self.assertEqual(self.p.render_timesyncd("time.example.net"),
            "[Time]\nNTP=\nNTP=time.example.net\nFallbackNTP=\n")
        with self.assertRaises(ValueError):
            self.p.render_timesyncd("time.example.net\nNTP=evil")

    def test_apt_new_install_architecture_is_not_an_upgrade(self):
        self.assertTrue(hasattr(self.p, "validate_apt_simulation"))
        self.p.validate_apt_simulation("Inst nfs-common (1:2.8.3-1 Debian:13.7/stable [arm64])\n", {"nfs-common"}, new_only=True)
        for text in ("Inst nfs-common [old] (new Debian [arm64])", "Remv linux-image-old [1]"):
            with self.assertRaises(ValueError):
                self.p.validate_apt_simulation(text, {"nfs-common"}, new_only=True)
