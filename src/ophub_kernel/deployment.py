import ipaddress
import hashlib
import json
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit


def render_sources(uri: str, keyring: str, enabled: bool = True) -> str:
    if re.search(r"\s", uri + keyring) or not Path(keyring).is_absolute():
        raise ValueError("unsafe source/keyring")
    parsed = urlsplit(uri)
    if parsed.scheme not in ("file", "https") or (parsed.scheme == "file" and not parsed.path.startswith("/")):
        raise ValueError("only absolute file or HTTPS sources supported")
    return (f"Types: deb\nURIs: {uri.rstrip('/')}/\nSuites: ./\nArchitectures: arm64\n"
            f"Signed-By: {keyring}\nEnabled: {'yes' if enabled else 'no'}\n")


def render_export(path: Path, client: str) -> str:
    if not path.is_absolute() or path.name != "wwwroot" or re.search(r"[\s()#]", str(path)) or ".." in path.parts:
        raise ValueError("only a safe absolute wwwroot directory may be exported")
    ipaddress.IPv4Address(client)
    return f"{path} {client}(ro,sync,no_subtree_check,root_squash)\n"


def render_timesyncd(server: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]*", server):
        raise ValueError("invalid NTP hostname")
    return f"[Time]\nNTP=\nNTP={server}\nFallbackNTP=\n"

def validate_apt_simulation(text: str, allowed: set[str], *, new_only=False) -> None:
    for line in text.splitlines():
        if line.startswith("Remv "):
            raise ValueError("simulation would remove an existing package")
        if line.startswith("Inst "):
            fields = line.split(maxsplit=2)
            if len(fields) != 3 or fields[1] not in allowed or (new_only and fields[2].startswith("[")):
                raise ValueError("unexpected package installation/upgrade: " + line)

def verified_manifest(repository: Path, keyring: Path, fingerprint: str, *, check_dates=True, check_packages=True) -> dict:
    with tempfile.TemporaryDirectory(prefix="verified-release-") as folder:
        decoded = Path(folder) / "Release"
        verification = subprocess.run(["gpgv", "--status-fd=1", "--keyring", str(keyring.resolve()),
            "--output", str(decoded), str(repository / "InRelease")], check=True, text=True, capture_output=True)
        if "[GNUPG:] VALIDSIG " + fingerprint.upper() + " " not in verification.stdout:
            raise ValueError("unexpected repository signing fingerprint")
        release = decoded.read_text()
        dates = dict(re.findall(r"(?m)^(Date|Valid-Until): (.+)$", release))
        now = datetime.now(timezone.utc)
        if check_dates and not parsedate_to_datetime(dates["Date"]) <= now <= parsedate_to_datetime(dates["Valid-Until"]):
            raise ValueError("repository metadata is not currently valid")
        hashes = {name: (digest, int(size)) for digest, size, name in
                  re.findall(r"(?m)^ ([0-9a-f]{64}) +([0-9]+) (\S+)$", release)}
        for name in ("Packages", "Packages.gz", "Packages.xz", "build-manifest.json"):
            path = repository / name
            if hashes.get(path.name) != (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size):
                raise ValueError("repository file differs from signed metadata: " + name)
        if (repository / 'Release').read_bytes() != decoded.read_bytes():
            raise ValueError('Release differs from authenticated InRelease body')
        path = repository / "build-manifest.json"
        manifest = json.loads(path.read_text())
        for record in manifest["packages"]:
            name = record["filename"]
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+\-]*\.deb", name):
                raise ValueError("unsafe package filename")
            package = repository / name
            if check_packages and (hashlib.sha256(package.read_bytes()).hexdigest(), package.stat().st_size) != (record["sha256"], record["size"]):
                raise ValueError("deployment package mismatch: " + name)
        return manifest
