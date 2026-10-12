import hashlib
import io
import json
import lzma
import re
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .model import Asset
from .deployment import verified_manifest

METADATA = {"Packages", "Packages.gz", "Packages.xz", "Release", "Release.gpg", "InRelease",
            "archive-keyring.gpg", "build-manifest.json", "SHA256SUMS", "index.html", "ophub-kernel.sources"}
GENERATION = "metadata-generation.tar.xz"
JOURNAL = "publication-journal.tar.xz"


def pack_generation(metadata: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name, data in sorted(metadata.items()):
            if name not in METADATA:
                raise ValueError("unexpected publication metadata")
            entry = tarfile.TarInfo(name)
            entry.size, entry.mode, entry.mtime = len(data), 0o644, 0
            archive.addfile(entry, io.BytesIO(data))
    return lzma.compress(stream.getvalue())


def unpack_generation(data: bytes, public_key: bytes, fingerprint: str) -> tuple[dict, dict]:
    limit = 32 * 1024**2
    if len(data) > limit:
        raise ValueError("publication generation exceeds limits")
    decoder = lzma.LZMADecompressor(memlimit=128 * 1024**2)
    raw = decoder.decompress(data, max_length=limit + 1)
    if len(raw) > limit or not decoder.eof:
        raise ValueError("expanded publication generation exceeds limits")
    metadata = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        for entry in archive.getmembers():
            if not entry.isfile() or entry.name not in METADATA or entry.name in metadata:
                raise ValueError("unsafe publication generation member")
            metadata[entry.name] = archive.extractfile(entry).read()
    if set(metadata) != METADATA or metadata['archive-keyring.gpg'] != public_key:
        raise ValueError("incomplete generation or unexpected repository public key")
    with tempfile.TemporaryDirectory(prefix="publication-auth-") as folder:
        path = Path(folder)
        for name, value in metadata.items():
            (path / name).write_bytes(value)
        trusted = path / "trusted.gpg"
        trusted.write_bytes(public_key)
        manifest = verified_manifest(path, trusted, fingerprint, check_dates=False, check_packages=False)
    return metadata, manifest


def check_remote_packages(client, release, manifest):
    assets = client.assets(release)
    for record in manifest["packages"]:
        asset = assets[record["filename"]]
        digest = asset.get("digest") or "sha256:" + hashlib.sha256(client.download(asset)).hexdigest()
        if digest != "sha256:" + record["sha256"]:
            raise ValueError("immutable remote package differs: " + record["filename"])


def recover_publication(client, release, public_key: bytes, fingerprint: str) -> None:
    assets = client.assets(release)
    if JOURNAL not in assets:
        return
    metadata, manifest = unpack_generation(client.download(assets[JOURNAL]), public_key, fingerprint)
    check_remote_packages(client, release, manifest)
    # The durable journal contains the complete authenticated NEW generation.
    # Roll forward after process/runner termination, then mark it committed.
    for name in sorted(METADATA - {"build-manifest.json"}) + ["build-manifest.json"]:
        current = client.assets(release)
        if name in current and client.download(current[name]) == metadata[name]:
            continue
        if name in current:
            client.delete(current[name])
        client.upload(release, name, metadata[name])
    client.delete(client.assets(release)[JOURNAL])


def needs_rebuild(asset: Asset, previous: dict | None, recipe_commit: str, dtb_sha256: str) -> bool:
    return not previous or previous.get("asset") != asset.fingerprint() or \
        previous.get("recipe_commit") != recipe_commit or previous.get("dtb_sha256") != dtb_sha256


class GitHubClient:
    def __init__(self, repo: str, token: str):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise ValueError("repository must be owner/repo")
        self.repo, self.token = repo, token
        self.base = "https://api.github.com/repos/" + repo

    def request(self, path, *, method="GET", data=None, url=None, content_type="application/json"):
        headers = {"User-Agent": "m13-ophub-kernel-debian", "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        if data is not None:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(url or self.base + path, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=180) as response:
            body = response.read()
            return json.loads(body) if body else None

    def release(self, tag):
        try:
            return self.request("/releases/tags/" + urllib.parse.quote(tag, safe=""))
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise

    def ensure_release(self, tag):
        existing = self.release(tag)
        return existing or self.request("/releases", method="POST", data=json.dumps(
            {"tag_name": tag, "name": tag, "draft": False, "prerelease": False,
             "make_latest": "false" if tag == "apt-6.12" else "true"}).encode())

    def assets(self, release):
        result, page = {}, 1
        while True:
            batch = self.request(f"/releases/{release['id']}/assets?per_page=100&page={page}")
            result.update({entry["name"]: entry for entry in batch})
            if len(batch) < 100:
                return result
            page += 1

    def download(self, asset):
        url = asset["browser_download_url"]
        expected = "https://github.com/" + self.repo + "/releases/download/"
        if not url.startswith(expected):
            raise ValueError("unexpected GitHub asset URL")
        with urllib.request.urlopen(url, timeout=180) as response:
            return response.read()

    def delete(self, asset):
        self.request(f"/releases/assets/{asset['id']}", method="DELETE")

    def upload(self, release, name, data):
        url = f"https://uploads.github.com/repos/{self.repo}/releases/{release['id']}/assets?name=" + urllib.parse.quote(name, safe="")
        self.request("", method="POST", data=data, url=url, content_type="application/octet-stream")


def publish_release(repo: str, wwwroot: Path, token: str, manifest: dict) -> dict:
    if not token:
        raise ValueError("publishing requires explicit GitHub token")
    public_key = (wwwroot / 'archive-keyring.gpg').read_bytes()
    fingerprint = manifest['signing_fingerprint']
    authenticated = verified_manifest(wwwroot, wwwroot / 'archive-keyring.gpg', fingerprint)
    if authenticated != manifest:
        raise ValueError('publication manifest is not the authenticated local manifest')
    client = GitHubClient(repo, token)
    version_tag = f"kernel-{manifest['kernel_release']}-m13.{manifest['revision']}"
    version = client.ensure_release(version_tag)
    apt = client.ensure_release("apt-6.12")
    recover_publication(client, apt, public_key, fingerprint)
    local = {path.name: path.read_bytes() for path in wwwroot.iterdir() if path.is_file()}
    immutable = sorted(name for name in local if name.endswith(".deb"))
    for record in manifest.get("packages", []):
        if record["filename"] not in local or hashlib.sha256(local[record["filename"]]).hexdigest() != record["sha256"]:
            raise ValueError("manifest package hash mismatch")
    # Check ALL existing packages before any mutation.
    for release in (version, apt):
        existing = client.assets(release)
        for name in immutable:
            if name in existing:
                remote_hash = existing[name].get("digest") or "sha256:" + hashlib.sha256(client.download(existing[name])).hexdigest()
                if remote_hash != "sha256:" + hashlib.sha256(local[name]).hexdigest():
                    raise ValueError("immutable remote package differs: " + name)
    previous_assets = client.assets(apt)
    if set(name for name in local if not name.endswith('.deb')) != METADATA:
        raise ValueError('unexpected public publication metadata files')
    metadata = sorted(METADATA - {"build-manifest.json"})
    backups = {name: client.download(previous_assets[name]) for name in metadata + ["build-manifest.json"] if name in previous_assets}
    for release in (version, apt):
        for name in immutable:
            if name not in client.assets(release):
                client.upload(release, name, local[name])
    snapshot = client.assets(version)
    snapshot_metadata = {name: local[name] for name in METADATA}
    if GENERATION in snapshot:
        snapshot_metadata, previous_manifest = unpack_generation(client.download(snapshot[GENERATION]), public_key, fingerprint)
        stable = lambda value: {key: data for key, data in value.items() if key not in ("metadata_generated_at", "metadata_only")}
        if stable(previous_manifest) != stable(manifest):
            raise ValueError('immutable snapshot build inputs differ')
    else:
        # Persist the first COMPLETE metadata generation before exposing any of
        # its individual immutable metadata assets; retries reuse these bytes.
        if any(name in snapshot for name in METADATA):
            raise ValueError('legacy incomplete snapshot has no durable generation; repair explicitly')
        client.upload(version, GENERATION, pack_generation(snapshot_metadata))
    # Immutable version snapshot is populated once; retries must match its bytes.
    for name in metadata + ["build-manifest.json"]:
        existing = client.assets(version)
        if name in existing:
            if client.download(existing[name]) != snapshot_metadata[name]:
                raise ValueError("immutable version snapshot differs: " + name)
        else:
            client.upload(version, name, snapshot_metadata[name])
    check_remote_packages(client, apt, manifest)
    # A fresh runner can authenticate and finish this generation even if the
    # process dies between delete/upload operations below.
    client.upload(apt, JOURNAL, pack_generation({name: local[name] for name in METADATA}))
    changed = []
    try:
        for name in metadata + ["build-manifest.json"]:
            existing = client.assets(apt)
            changed.append(name)
            if name in existing:
                client.delete(existing[name])
            client.upload(apt, name, local[name])
    except Exception:
        for name in reversed(changed):
            existing = client.assets(apt)
            if name in existing:
                client.delete(existing[name])
            if name in backups:
                client.upload(apt, name, backups[name])
        client.delete(client.assets(apt)[JOURNAL])
        raise
    client.delete(client.assets(apt)[JOURNAL])
    return {"version_tag": version_tag, "apt_tag": "apt-6.12", "repository": repo}
