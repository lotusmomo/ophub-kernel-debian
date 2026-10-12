import importlib
import io
import tarfile
import tempfile
import unittest
from pathlib import Path


def make_tar(path, members):
    with tarfile.open(path, "w:gz") as archive:
        for name, kind, target in members:
            member = tarfile.TarInfo(name)
            if kind == "file":
                member.size = len(target)
                archive.addfile(member, io.BytesIO(target))
            elif kind == "dir":
                member.type = tarfile.DIRTYPE
                archive.addfile(member)
            else:
                member.type = tarfile.SYMTYPE if kind == "link" else tarfile.LNKTYPE
                member.linkname = target
                archive.addfile(member)


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        try:
            self.p = importlib.import_module("ophub_kernel.archive")
        except ModuleNotFoundError:
            self.p = None
        self.assertIsNotNone(self.p, "archive implementation missing")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def unpack(self, members, **kwargs):
        path = self.root / "in.tar.gz"
        make_tar(path, members)
        return self.p.safe_extract(path, self.root / "out", **kwargs)

    def test_extract_regular_file(self):
        self.unpack([("release/a", "file", b"abc")])
        self.assertEqual((self.root / "out/release/a").read_bytes(), b"abc")

    def test_traversal_absolute_and_escaping_link_rejected_before_write(self):
        for members in [[("../outside", "file", b"bad")], [("/outside", "file", b"bad")],
                        [("jump", "link", "../outside"), ("jump/child", "file", b"bad")],
                        [("jump", "hard", "/etc/passwd")]]:
            with self.subTest(members=members), self.assertRaises(ValueError):
                self.unpack(members)
        self.assertFalse((self.root / "outside").exists())

    def test_duplicate_paths_rejected(self):
        with self.assertRaises(ValueError):
            self.unpack([("a", "file", b"a"), ("a", "file", b"b")])

    def test_modules_external_build_link_only_is_skipped(self):
        self.unpack([("6.12.112-ophub/build", "link", "/build/kernel"),
                     ("6.12.112-ophub/kernel/a", "file", b"ok")], skip_module_links=True)
        self.assertFalse((self.root / "out/6.12.112-ophub/build").exists())
        self.assertTrue((self.root / "out/6.12.112-ophub/kernel/a").exists())

    def test_normalized_dot_duplicate_rejected(self):
        with self.assertRaises(ValueError):
            self.unpack([("./a", "file", b"a"), ("a", "file", b"b")])
