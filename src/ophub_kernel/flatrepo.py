import gzip
import html
import json
import lzma
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

from .deployment import render_sources
from .upstream import sha256_file


def build_repository(packages: list[Path], output: Path, signing_home: Path,
                     fingerprint: str, manifest: dict) -> Path:
    home = signing_home.resolve()
    destination = output.resolve()
    if not home.is_dir() or (home.stat().st_mode & 0o077):
        raise ValueError("signing home must exist and be owner-only")
    if home.is_relative_to(destination) or destination.is_relative_to(home):
        raise ValueError("signing keys cannot be inside exported artifacts")
    if not re.fullmatch(r"[0-9A-Fa-f]{40,64}", fingerprint):
        raise ValueError("invalid signing fingerprint")
    if output.is_symlink():
        raise ValueError("repository directory must not be a symlink")
    encoded = json.dumps(manifest)
    if "PRIVATE KEY" in encoded or re.search(r'"(?:token|password|secret|private_key)"\s*:', encoded, re.I):
        raise ValueError("private material cannot enter public manifest")
    output.mkdir(parents=True, exist_ok=True)
    output.chmod(0o755)
    for source in packages:
        if source.is_symlink() or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+\-]*\.deb", source.name):
            raise ValueError("invalid package path")
        target = output / source.name
        if target.exists() and sha256_file(target) != sha256_file(source):
            raise ValueError("refusing to overwrite immutable package")
        if target.resolve() != source.resolve():
            shutil.copyfile(source, target)
        target.chmod(0o644)
    for path in output.iterdir():
        if not path.is_file() or path.is_symlink():
            raise ValueError("flat public repository must contain regular files only")
    scanned = subprocess.check_output(["dpkg-scanpackages", "--multiversion", ".", "/dev/null"],
                                      cwd=output, text=True, stderr=subprocess.PIPE)
    scanned = re.sub(r"(?m)^Filename: \./", "Filename: ", scanned)
    (output / "Packages").write_text(scanned)
    (output / "Packages.gz").write_bytes(gzip.compress(scanned.encode(), mtime=0))
    (output / "Packages.xz").write_bytes(lzma.compress(scanned.encode()))
    now = datetime.now(timezone.utc)
    release = ("Origin: M13-ophub-6.12\nLabel: M13 ophub stable 6.12\nSuite: apt-6.12\n"
               "Codename: apt-6.12\nArchitectures: arm64 all\n"
               f"Date: {format_datetime(now, usegmt=True)}\n"
               f"Valid-Until: {format_datetime(now + timedelta(days=7), usegmt=True)}\nSHA256:\n")
    for name in ("Packages", "Packages.gz", "Packages.xz"):
        path = output / name
        release += f" {sha256_file(path)} {path.stat().st_size:16d} {name}\n"
    (output / "Release").write_text(release)
    base = ["gpg", "--homedir", str(home), "--batch", "--yes", "--local-user", fingerprint]
    subprocess.run(base + ["--digest-algo", "SHA256", "--clearsign", "--output", str(output / "InRelease"),
                           str(output / "Release")], check=True, capture_output=True)
    subprocess.run(base + ["--digest-algo", "SHA256", "--detach-sign", "--output", str(output / "Release.gpg"),
                           str(output / "Release")], check=True, capture_output=True)
    public = subprocess.check_output(base + ["--export", fingerprint])
    if not public:
        raise ValueError("public key export empty")
    (output / "archive-keyring.gpg").write_bytes(public)
    records = []
    for package in sorted(output.glob("*.deb")):
        control = subprocess.check_output(["dpkg-deb", "--field", str(package)], text=True)
        fields = dict(line.split(": ", 1) for line in control.splitlines() if ": " in line)
        records.append({"filename": package.name, "sha256": sha256_file(package), "size": package.stat().st_size,
                        "package": fields["Package"], "version": fields["Version"], "architecture": fields["Architecture"]})
    published = dict(manifest, packages=records, signing_fingerprint=fingerprint,
                     metadata_generated_at=now.isoformat(), origin="M13-ophub-6.12")
    (output / "build-manifest.json").write_text(json.dumps(published, indent=2) + "\n")
    (output / "ophub-kernel.sources").write_text(render_sources(
        "file:/mnt/ophub-kernel/", "/etc/apt/keyrings/ophub-kernel.gpg"))
    (output / "index.html").write_text("<!doctype html><meta charset=utf-8><title>M13 kernel artifacts</title>\n" +
        "\n".join(f'<p><a href="{html.escape(p.name)}">{html.escape(p.name)}</a></p>' for p in sorted(output.iterdir())))
    sums = "".join(f"{sha256_file(path)}  {path.name}\n" for path in sorted(output.iterdir())
                   if path.name != "SHA256SUMS")
    (output / "SHA256SUMS").write_text(sums)
    for path in output.iterdir():
        path.chmod(0o644)
    subprocess.run(["gpgv", "--keyring", str((output / "archive-keyring.gpg").resolve()),
                    str(output / "InRelease")], check=True, capture_output=True)
    return output
