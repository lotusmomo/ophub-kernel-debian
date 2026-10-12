import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .model import Asset


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
    client = GitHubClient(repo, token)
    version_tag = f"kernel-{manifest['kernel_release']}-m13.{manifest['revision']}"
    version = client.ensure_release(version_tag)
    apt = client.ensure_release("apt-6.12")
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
    metadata = sorted(name for name in local if not name.endswith(".deb") and name != "build-manifest.json")
    backups = {name: client.download(previous_assets[name]) for name in metadata + ["build-manifest.json"] if name in previous_assets}
    for release in (version, apt):
        for name in immutable:
            if name not in client.assets(release):
                client.upload(release, name, local[name])
    snapshot = client.assets(version)
    preserve_snapshot = manifest.get("metadata_only", False)
    if "build-manifest.json" in snapshot and client.download(snapshot["build-manifest.json"]) != local["build-manifest.json"]:
        previous_manifest = json.loads(client.download(snapshot["build-manifest.json"]))
        stable = lambda value: {key: data for key, data in value.items()
                                if key not in ("metadata_generated_at", "metadata_only")}
        if stable(previous_manifest) != stable(manifest):
            raise ValueError("immutable snapshot build inputs differ")
        preserve_snapshot = True
    # Immutable version snapshot is populated once; retries must match its bytes.
    for name in metadata + ["build-manifest.json"]:
        existing = client.assets(version)
        if name in existing:
            if not preserve_snapshot and client.download(existing[name]) != local[name]:
                raise ValueError("immutable version snapshot differs: " + name)
        else:
            client.upload(version, name, local[name])
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
        raise
    return {"version_tag": version_tag, "apt_tag": "apt-6.12", "repository": repo}
