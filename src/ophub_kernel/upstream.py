import hashlib
import json
import re
import urllib.request
from pathlib import Path

from .model import Asset

API = "https://api.github.com/repos/ophub/kernel/releases/tags/kernel_stable"


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fetch_release() -> dict:
    request = urllib.request.Request(API, headers={"User-Agent": "ophub-kernel-debian"})
    with urllib.request.urlopen(request, timeout=60) as stream:
        return json.load(stream)


def select_asset(release_json: dict, series: str = "6.12") -> Asset:
    if series != "6.12":
        raise ValueError("only stable 6.12 is supported")
    candidates = []
    for item in release_json.get("assets", []):
        match = re.fullmatch(r"(6\.12\.[0-9]+)\.tar\.gz", item.get("name", ""))
        if match:
            candidates.append((tuple(map(int, match[1].split("."))), item))
    if not candidates:
        raise ValueError("no stable 6.12 tarball")
    _, item = max(candidates, key=lambda candidate: candidate[0])
    digest = item.get("digest") or ""
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("upstream SHA256 digest missing or invalid")
    url = item.get("browser_download_url", "")
    expected = "https://github.com/ophub/kernel/releases/download/kernel_stable/" + item["name"]
    if url != expected or int(item["size"]) <= 0:
        raise ValueError("invalid upstream URL or size")
    return Asset(item["name"], item["name"][:-7], int(item["id"]), item["updated_at"],
                 url, digest[7:], int(item["size"]))


def download_asset(asset: Asset, cache: Path) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / asset.name
    if target.exists():
        if target.stat().st_size == asset.size and sha256_file(target) == asset.sha256:
            return target
        raise ValueError("cached asset differs; preserve it and use a new cache directory")
    partial = cache / (asset.name + ".partial")
    if partial.exists():
        raise ValueError("partial download exists; inspect it before retrying")
    request = urllib.request.Request(asset.url, headers={"User-Agent": "ophub-kernel-debian"})
    size = 0
    with urllib.request.urlopen(request, timeout=120) as src, partial.open("xb") as dst:
        while block := src.read(1024 * 1024):
            size += len(block)
            if size > asset.size:
                raise ValueError("download larger than declared asset")
            dst.write(block)
    if size != asset.size or sha256_file(partial) != asset.sha256:
        raise ValueError("download SHA256/size mismatch; partial file retained")
    partial.rename(target)
    return target
