import re
import shutil
import subprocess
import tarfile
from pathlib import Path, PurePosixPath

from .model import Asset, ValidatedKernel
from .upstream import sha256_file

M13_DTB_SHA256 = "08ebca98b5049d95bcf270374d41f608edc19658392f3c1b35fcf904e8b6f927"


def safe_extract(archive: Path, output: Path, *, skip_module_links=False):
    if output.is_symlink() or (output.exists() and any(output.iterdir())):
        raise ValueError("extraction directory must be empty and not a symlink")
    with tarfile.open(archive, "r:*") as source:
        members = source.getmembers()
        if len(members) > 100000 or sum(member.size for member in members) > 2 * 1024**3:
            raise ValueError("archive expansion exceeds limits")
        seen, approved = set(), []
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or "\\" in member.name or "\x00" in member.name:
                raise ValueError("unsafe archive path: " + member.name)
            name = str(path)
            if name == "." and member.isdir():
                continue
            if name in seen:
                raise ValueError("duplicate archive member: " + name)
            seen.add(name)
            if skip_module_links and member.issym() and len(path.parts) == 2 and \
               re.fullmatch(r"6\.12\.[0-9]+-ophub", path.parts[0]) and path.name in ("build", "source"):
                continue
            if not (member.isfile() or member.isdir()):
                raise ValueError("archive links/devices are not allowed: " + name)
            approved.append((member, path))
        file_names = {str(path) for member, path in approved if member.isfile()}
        for _, path in approved:
            if any(str(parent) in file_names for parent in path.parents):
                raise ValueError("archive file used as a parent")
        output.mkdir(parents=True, exist_ok=True)
        for member, path in approved:
            target = output / str(path)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                target.chmod(0o755)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as src, target.open("xb") as dst:
                    shutil.copyfileobj(src, dst)
                target.chmod(0o644)
    return output


def read_config(path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in path.read_text().splitlines()
                if line.startswith("CONFIG_") and "=" in line)


def validate_bundle(bundle: Path, asset: Asset, workspace: Path, m13_dtb: Path) -> ValidatedKernel:
    if sha256_file(bundle) != asset.sha256 or bundle.stat().st_size != asset.size:
        raise ValueError("outer asset hash or size mismatch")
    if sha256_file(m13_dtb) != M13_DTB_SHA256:
        raise ValueError("M13 DTB differs from verified board input")
    outer = safe_extract(bundle, workspace / "outer")
    inner = outer / asset.version
    sums = {}
    for line in (inner / "sha256sums").read_text().splitlines():
        if not line.strip():
            continue
        digest, name = line.split(maxsplit=1)
        name = name.lstrip("*")
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or "/" in name or name in sums:
            raise ValueError("invalid inner checksum manifest")
        sums[name] = digest
    release = asset.version + "-ophub"
    directories = {}
    for category, prefix in (("boot", "boot"), ("modules", "modules"), ("dtb", "dtb-amlogic")):
        name = f"{prefix}-{release}.tar.gz"
        if name not in sums or sha256_file(inner / name) != sums[name]:
            raise ValueError("inner hash mismatch: " + name)
        directories[category] = safe_extract(inner / name, workspace / category,
                                             skip_module_links=category == "modules")
    modules = directories["modules"] / release
    config = read_config(directories["boot"] / f"config-{release}")
    for capability in ("CONFIG_F2FS_FS", "CONFIG_BLK_DEV_DM", "CONFIG_MMC_BLOCK", "CONFIG_MMC_MESON_GX"):
        if config.get(capability) not in ("y", "m"):
            raise ValueError("required boot capability missing: " + capability)
    image = directories["boot"] / f"vmlinuz-{release}"
    if not image.is_file() or image.stat().st_size < 64:
        raise ValueError("kernel image missing")
    with image.open("rb") as stream:
        header = stream.read(64)
    if header[56:60] != b"ARMd":
        raise ValueError("expected uncompressed ARM64 Image for existing booti path")
    module_files = sorted(modules.rglob("*.ko*"))
    if not module_files:
        raise ValueError("module payload missing")
    modinfo = shutil.which("modinfo") or "/usr/sbin/modinfo"
    for module in module_files:
        vermagic = subprocess.check_output([modinfo, "-F", "vermagic", str(module)], text=True).strip()
        if not vermagic or vermagic.split()[0] != release:
            raise ValueError("module release mismatch: " + str(module))
    return ValidatedKernel(release, directories["boot"], modules, directories["dtb"], config, m13_dtb)
