import importlib
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from ophub_kernel.model import ValidatedKernel


class DebianTests(unittest.TestCase):
    def setUp(self):
        try:
            self.p = importlib.import_module("ophub_kernel.debian")
        except ModuleNotFoundError:
            self.p = None
        self.assertIsNotNone(self.p, "debian packaging implementation missing")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        boot, modules, dtb = [self.root / name for name in ("boot", "modules", "dtb")]
        for path in (boot, modules, dtb):
            path.mkdir()
        for name in ("vmlinuz", "config", "System.map", "initrd.img", "uInitrd"):
            (boot / (name + "-6.12.112-ophub")).write_bytes(b"fixture " + name.encode())
        (modules / "modules.order").write_text("")
        (modules / "module.ko").write_bytes(b"module fixture")
        m13 = self.root / "m13.dtb"
        m13.write_bytes(b"dtb fixture")
        self.kernel = ValidatedKernel("6.12.112-ophub", boot, modules, dtb, {}, m13)

    def test_three_packages_dependency_and_payload_contract(self):
        files = self.p.build_packages(self.kernel, 1, self.root / "out", {"fixture": True})
        fields = {}
        for path in files:
            text = subprocess.check_output(["dpkg-deb", "--field", str(path)], text=True)
            fields[text.split("Package: ")[1].splitlines()[0]] = text
            self.assertNotIn("Conflicts:", text)
            self.assertNotIn("Replaces:", text)
        self.assertEqual(len(files), 3)
        self.assertIn("Version: 1:6.12.112-1+m13.1", fields["linux-image-arm64"])
        self.assertIn("Depends: linux-image-6.12.112-ophub (= 6.12.112-1+m13.1)", fields["linux-image-arm64"])
        image = next(path for path in files if path.name.startswith("linux-image-6.12."))
        listing = subprocess.check_output(["dpkg-deb", "--contents", str(image)], text=True)
        self.assertIn("usr/lib/modules/6.12.112-ophub/module.ko", listing)
        self.assertIn("boot/dtbs/6.12.112-ophub/amlogic/meson-gxbb-tianmao-m13.dtb", listing)
        self.assertNotIn("initrd.img-", listing)
        self.assertNotIn("uInitrd-", listing)
        self.assertTrue(all(":" not in path.name for path in files))

    def test_revision_change_changes_version(self):
        files = self.p.build_packages(self.kernel, 42, self.root / "out", {})
        self.assertTrue(all("m13.42" in path.name for path in files))

    def test_existing_deb_never_overwritten(self):
        files = self.p.build_packages(self.kernel, 1, self.root / "out", {})
        original = files[0].read_bytes()
        with self.assertRaises(ValueError):
            self.p.build_packages(self.kernel, 1, self.root / "out", {})
        self.assertEqual(files[0].read_bytes(), original)

    def test_identical_payload_reproducible_across_extraction_mtimes(self):
        first = self.p.build_packages(self.kernel, 1, self.root / "first", {})
        os.utime(self.kernel.modules_dir / "module.ko", (100, 100))
        second = self.p.build_packages(self.kernel, 1, self.root / "second", {})
        self.assertEqual([path.read_bytes() for path in first], [path.read_bytes() for path in second])

    def test_postinst_propagates_hook_failure(self):
        files = self.p.build_packages(self.kernel, 1, self.root / "out", {})
        image = next(path for path in files if path.name.startswith("linux-image-6.12."))
        sandbox = self.root / "sandbox"
        sandbox.mkdir()
        for executable in ("/bin/dash", "/usr/bin/run-parts"):
            dest = sandbox / executable.lstrip("/")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(executable, dest)
            libraries = subprocess.check_output(["ldd", executable], text=True)
            for library in re.findall(r"(/[^\s()]+)", libraries):
                destination = sandbox / library.lstrip("/")
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(library, destination)
        (sandbox / "bin/sh").symlink_to("dash")
        (sandbox / "boot").mkdir()
        old = sandbox / "boot/vmlinuz-old"
        old.write_text("preserve")
        (sandbox / "usr/sbin").mkdir(parents=True)
        depmod = sandbox / "usr/sbin/depmod"
        depmod.write_text("#!/bin/sh\nexit 0\n")
        depmod.chmod(0o755)
        hookdir = sandbox / "etc/kernel/postinst.d"
        hookdir.mkdir(parents=True)
        hook = hookdir / "fail"
        hook.write_text("#!/bin/sh\nexit 23\n")
        hook.chmod(0o755)
        subprocess.run(["dpkg-deb", "--control", str(image), str(sandbox / "control")], check=True)
        prefix = [] if os.geteuid() == 0 else ["sudo", "-n"]
        command = prefix + ["/usr/sbin/chroot", str(sandbox), "/bin/sh", "/control/postinst", "configure"]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(old.read_text(), "preserve")
        hook.write_text('#!/bin/sh\nprintf initramfs > "/boot/initrd.img-$1"\n')
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
        self.assertEqual(old.read_text(), "preserve")
