import importlib
import hashlib
import io
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from ophub_kernel.model import Asset


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

    def test_image_banner_binds_actual_release_to_modules(self):
        self.assertTrue(hasattr(self.p, "validate_image"), "actual Image release check missing")
        image = self.root / "Image"
        header = bytes(56) + b"ARMd" + bytes(4)
        image.write_bytes(header + b"Linux version 6.12.112-ophub (fixture)\x00")
        self.p.validate_image(image, "6.12.112-ophub")
        with self.assertRaises(ValueError):
            self.p.validate_image(image, "6.12.113-ophub")

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

    def test_generic_bundle_does_not_require_a_board_dtb_or_f2fs(self):
        release = "6.12.112-ophub"
        module = self.root / "fixture.ko"
        subprocess.run(["cc", "-x", "c", "-c", "-o", str(module), "-"],
            input='const char vermagic[] __attribute__((section(".modinfo"))) = "vermagic=6.12.112-ophub SMP";',
            text=True, check=True, capture_output=True)
        inputs = {
            "boot": [(f"vmlinuz-{release}", "file", bytes(56) + b"ARMd" + bytes(4) + b"Linux version 6.12.112-ophub (fixture) "),
                     (f"config-{release}", "file", b"CONFIG_MMC_BLOCK=y\n"),
                     (f"System.map-{release}", "file", b"fixture")],
            "modules": [(f"{release}/fixture.ko", "file", module.read_bytes())],
            "dtb-amlogic": [("meson-gxbb-p200.dtb", "file", b"upstream dtb")],
        }
        members, checksums = [], []
        for category, entries in inputs.items():
            name = f"{category}-{release}.tar.gz"
            archive = self.root / name
            make_tar(archive, entries)
            data = archive.read_bytes()
            checksums.append(hashlib.sha256(data).hexdigest() + "  " + name)
            members.append(("6.12.112/" + name, "file", data))
        members.append(("6.12.112/sha256sums", "file", ("\n".join(checksums) + "\n").encode()))
        bundle = self.root / "6.12.112.tar.gz"
        make_tar(bundle, members)
        selected = Asset(bundle.name, "6.12.112", 1, "2026-10-05T00:00:00Z", "https://github.com/ophub/kernel/releases/download/kernel_stable/6.12.112.tar.gz",
                         hashlib.sha256(bundle.read_bytes()).hexdigest(), bundle.stat().st_size)
        try:
            kernel = self.p.validate_bundle(bundle, selected, self.root / "validated", None)
        except (TypeError, ValueError, AttributeError) as error:
            self.fail("generic validation must not require an M13 board input: " + str(error))
        self.assertIsNone(kernel.m13_dtb)
        self.assertEqual(kernel.release, "6.12.112-ophub")
