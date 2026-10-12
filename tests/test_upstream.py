import hashlib
import importlib
import unittest


def production(name):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError:
        return None


def asset(name, digest="a" * 64, ident=1):
    return {"name": name, "id": ident, "updated_at": "2026-10-05T03:32:39Z",
            "size": 123, "digest": "sha256:" + digest,
            "browser_download_url": "https://github.com/ophub/kernel/releases/download/kernel_stable/" + name}


class UpstreamTests(unittest.TestCase):
    def setUp(self):
        self.p = production("ophub_kernel.upstream")
        self.assertIsNotNone(self.p, "upstream implementation missing")

    def test_numeric_sort_not_lexical(self):
        result = self.p.select_asset({"assets": [asset("6.12.99.tar.gz"), asset("6.12.112.tar.gz")]})
        self.assertEqual(result.version, "6.12.112")

    def test_other_formats_and_series_excluded(self):
        result = self.p.select_asset({"assets": [asset(n) for n in
            ["6.12.112.tar.gz", "deb-6.12.999.tar.gz", "6.18.900.tar.gz", "6.12.999-rc1.tar.gz"]]})
        self.assertEqual(result.name, "6.12.112.tar.gz")

    def test_missing_digest_rejected(self):
        value = asset("6.12.112.tar.gz")
        value["digest"] = None
        with self.assertRaises(ValueError):
            self.p.select_asset({"assets": [value]})

    def test_unapproved_download_host_rejected(self):
        value = asset("6.12.112.tar.gz")
        value["browser_download_url"] = "http://attacker.invalid/kernel.tar.gz"
        with self.assertRaises(ValueError):
            self.p.select_asset({"assets": [value]})

    def test_no_candidate_fails_closed(self):
        with self.assertRaises(ValueError):
            self.p.select_asset({"assets": []})

    def test_file_checksum_uses_bytes(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture"
            path.write_bytes(b"abc")
            self.assertEqual(self.p.sha256_file(path), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")

