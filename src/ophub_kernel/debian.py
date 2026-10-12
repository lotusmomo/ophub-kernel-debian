import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .model import ValidatedKernel

COPYRIGHT = """Linux kernel image and modules: Copyright Linux kernel contributors.
License: GPL-2.0-only; see /usr/share/common-licenses/GPL-2.
M13 DTB based on Meson board descriptions: GPL-2.0+ OR MIT.
Packaging tools: GPL-2.0-only.
Upstream kernel and build sources: https://github.com/ophub/kernel#kernel-source-code
https://github.com/unifreq/linux-6.12.y
https://github.com/ophub/amlogic-s9xxx-armbian/tree/main/compile-kernel
The config and packaging provenance are included; binaries are not ABI-renamed.
"""


def _write(path: Path, text: str, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)


def build_packages(kernel: ValidatedKernel, revision: int, output: Path, provenance: dict) -> list[Path]:
    if not re.fullmatch(r"6\.12\.[0-9]+-ophub", kernel.release) or revision < 1:
        raise ValueError("invalid kernel release/revision")
    upstream_version = kernel.release.removesuffix("-ophub")
    version = f"{upstream_version}-1+m13.{revision}"
    image_name = "linux-image-" + kernel.release
    specs = [(image_name, version, "arm64", "linux-base, kmod, initramfs-tools"),
             ("linux-image-arm64", "1:" + version, "arm64", f"{image_name} (= {version})"),
             ("m13-boot-support", version, "all", "u-boot-menu")]
    output.mkdir(parents=True, exist_ok=True)
    targets = [output / f"{name}_{version}_{arch}.deb" for name, _, arch, _ in specs]
    if any(target.exists() for target in targets):
        raise ValueError("published package versions are immutable; select a new revision")
    with tempfile.TemporaryDirectory(prefix="package-", dir=output) as temporary:
        for (name, control_version, arch, depends), target in zip(specs, targets):
            stage = Path(temporary) / name
            stage.mkdir()
            doc = stage / "usr/share/doc" / name
            _write(doc / "copyright", COPYRIGHT)
            _write(doc / "provenance.json", json.dumps(provenance, indent=2) + "\n")
            if name == image_name:
                for prefix in ("vmlinuz", "config", "System.map"):
                    filename = f"{prefix}-{kernel.release}"
                    destination = stage / "boot" / filename
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(kernel.boot_dir / filename, destination)
                shutil.copytree(kernel.modules_dir, stage / "usr/lib/modules" / kernel.release)
                dtbs = stage / "usr/lib" / image_name / "amlogic"
                shutil.copytree(kernel.dtb_dir, dtbs)
                shutil.copyfile(kernel.m13_dtb, dtbs / "meson-gxbb-tianmao-m13.dtb")
                boot_dtb = stage / "boot/dtbs" / kernel.release / "amlogic/meson-gxbb-tianmao-m13.dtb"
                boot_dtb.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(kernel.m13_dtb, boot_dtb)
                for script in ("postinst", "prerm", "postrm"):
                    template = Path(__file__).resolve().parents[2] / "packaging" / f"image.{script}"
                    _write(stage / "DEBIAN" / script, template.read_text().replace("@KREL@", kernel.release), 0o755)
            elif name == "m13-boot-support":
                template = Path(__file__).resolve().parents[2] / "packaging/m13-u-boot.conf"
                _write(stage / "usr/share/u-boot-menu/conf.d/40-m13.conf", template.read_text())
            size = (sum(p.stat().st_size for p in stage.rglob("*") if p.is_file()) + 1023) // 1024
            control = (f"Package: {name}\nVersion: {control_version}\nArchitecture: {arch}\n"
                       "Maintainer: M13 kernel packaging <noreply@localhost>\n"
                       f"Installed-Size: {size}\nDepends: {depends}\nSection: kernel\nPriority: optional\n"
                       f"Description: M13 ophub stable kernel {kernel.release}\n"
                       " Debian-managed kernel packaging with preserved boot firmware.\n")
            if name == "linux-image-arm64":
                control += "Recommends: m13-boot-support\n"
            elif name == image_name:
                control += "Recommends: u-boot-menu\n"
            _write(stage / "DEBIAN/control", control)
            subprocess.run(["dpkg-deb", "--root-owner-group", "-Zxz", "--build", str(stage), str(target)],
                           check=True, stdout=subprocess.PIPE)
    return targets
