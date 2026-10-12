import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .archive import M13_DTB_SHA256, validate_bundle
from .debian import build_packages
from .flatrepo import build_repository
from .github import GitHubClient, needs_rebuild, publish_release, recover_publication
from .upstream import download_asset, fetch_release, select_asset, sha256_file

ROOT = Path(__file__).resolve().parents[2]


def recipe_commit():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def check_cached_inputs(output: Path, manifest: dict, asset, recipe: str, dtb: str):
    if needs_rebuild(asset, manifest, recipe, dtb):
        raise ValueError("cached build inputs changed; use a new revision")
    hashes = manifest.get("package_hashes", {})
    if not hashes:
        raise ValueError("cached build lacks package hashes; use a new revision")
    for name, digest in hashes.items():
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+\-]*\.deb", name) or sha256_file(output / name) != digest:
            raise ValueError("cached package integrity failure")


def prepare_packages(cache: Path, output: Path, revision: int):
    asset = select_asset(fetch_release())
    bundle = download_asset(asset, cache)
    workspace = Path(tempfile.mkdtemp(prefix="validated-", dir=cache))
    kernel = validate_bundle(bundle, asset, workspace, ROOT / "assets/m13/meson-gxbb-tianmao-m13.dtb")
    manifest = {"asset": asset.fingerprint(), "recipe_commit": recipe_commit(),
                "dtb_sha256": M13_DTB_SHA256, "kernel_release": kernel.release, "revision": revision,
                "config": {name: kernel.config.get(name) for name in ("CONFIG_F2FS_FS", "CONFIG_BLK_DEV_DM",
                    "CONFIG_MMC_MESON_GX", "CONFIG_CMDLINE_PARTITION", "CONFIG_DWMAC_MESON", "CONFIG_ICPLUS_PHY")},
                "source_reference": "https://github.com/ophub/kernel#kernel-source-code",
                "source_repository": "https://github.com/unifreq/linux-6.12.y"}
    packages = build_packages(kernel, revision, output, manifest)
    manifest["package_hashes"] = {p.name: sha256_file(p) for p in packages}
    (output / "build-input.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return packages, manifest


def restore_previous(repo: str, output: Path, home: Path, fingerprint: str):
    client = GitHubClient(repo, os.environ.get("GITHUB_TOKEN", ""))
    release = client.release("apt-6.12")
    if not release:
        return None
    public = subprocess.check_output(["gpg", "--homedir", str(home), "--batch", "--export", fingerprint])
    recover_publication(client, release, public, fingerprint)
    assets = client.assets(release)
    if 'InRelease' not in assets:
        if not any(name in assets for name in ('Packages', 'Release', 'build-manifest.json')):
            return None
        raise ValueError('incomplete release without an authenticated recovery journal')
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="previous-") as directory:
        temp = Path(directory)
        for name in ("InRelease", "Packages", "build-manifest.json"):
            (temp / name).write_bytes(client.download(assets[name]))
        (temp / "keyring.gpg").write_bytes(public)
        subprocess.run(["gpgv", "--keyring", str(temp / "keyring.gpg"), "--output", str(temp / "decoded"),
                        str(temp / "InRelease")], check=True, capture_output=True)
        signed_hashes = {name: (digest, int(size)) for digest, size, name in
                         re.findall(r"(?m)^ ([0-9a-f]{64}) +([0-9]+) (\S+)$", (temp / "decoded").read_text())}
        for name in ("Packages", "build-manifest.json"):
            if signed_hashes.get(name) != (sha256_file(temp / name), (temp / name).stat().st_size):
                raise ValueError("previous repository signed hash mismatch: " + name)
        for block in (temp / "Packages").read_text().strip().split("\n\n"):
            if not block:
                continue
            fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line and not line.startswith(" "))
            name = fields["Filename"]
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+\-]*\.deb", name):
                raise ValueError("previous package path unsafe")
            data = client.download(assets[name])
            if hashlib.sha256(data).hexdigest() != fields["SHA256"] or len(data) != int(fields["Size"]):
                raise ValueError("previous signed package hash mismatch")
            target = output / name
            if target.exists() and target.read_bytes() != data:
                raise ValueError("local immutable package mismatch")
            target.write_bytes(data)
        return json.loads((temp / "build-manifest.json").read_text())


def main():
    parser = argparse.ArgumentParser(description="M13 Debian kernel packaging (never flashes firmware)")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check-upstream")
    check.add_argument("--from-json", type=Path)
    build = sub.add_parser("build")
    build.add_argument("--cache", type=Path, default=ROOT / ".cache")
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--revision", type=int, required=True)
    cache_check = sub.add_parser("check-build")
    cache_check.add_argument("--packages", type=Path, required=True)
    repository = sub.add_parser("repository")
    repository.add_argument("--packages", type=Path, required=True)
    repository.add_argument("--output", type=Path, required=True)
    repository.add_argument("--signing-home", type=Path, required=True)
    repository.add_argument("--fingerprint", required=True)
    publish = sub.add_parser("publish")
    publish.add_argument("--repo", required=True)
    publish.add_argument("--output", type=Path, required=True)
    sync = sub.add_parser("sync")
    sync.add_argument("--repo", required=True)
    sync.add_argument("--cache", type=Path, default=ROOT / ".cache")
    sync.add_argument("--output", type=Path, default=ROOT / "wwwroot")
    sync.add_argument("--revision", type=int, required=True)
    sync.add_argument("--signing-home", type=Path, required=True)
    sync.add_argument("--fingerprint", required=True)
    args = parser.parse_args()
    try:
        if args.command == "check-upstream":
            data = json.loads(args.from_json.read_text()) if args.from_json else fetch_release()
            print(json.dumps(select_asset(data).fingerprint(), indent=2))
        elif args.command == "build":
            packages, manifest = prepare_packages(args.cache, args.output, args.revision)
            print(json.dumps({"packages": [str(p) for p in packages], "kernel_release": manifest["kernel_release"]}, indent=2))
        elif args.command == "check-build":
            manifest = json.loads((args.packages / "build-input.json").read_text())
            check_cached_inputs(args.packages, manifest, select_asset(fetch_release()), recipe_commit(),
                                sha256_file(ROOT / "assets/m13/meson-gxbb-tianmao-m13.dtb"))
            print("Cached inputs and package hashes verified")
        elif args.command == "repository":
            manifest = json.loads((args.packages / "build-input.json").read_text())
            build_repository(sorted(args.packages.glob("*.deb")), args.output, args.signing_home,
                             args.fingerprint, manifest)
            print(str(args.output))
        elif args.command == "publish":
            if not os.environ.get("GITHUB_TOKEN"):
                raise ValueError("GITHUB_TOKEN required for explicit publishing")
            subprocess.run(["gpgv", "--keyring", str((args.output / "archive-keyring.gpg").resolve()),
                            str(args.output / "InRelease")], check=True, capture_output=True)
            manifest = json.loads((args.output / "build-manifest.json").read_text())
            print(json.dumps(publish_release(args.repo, args.output, os.environ["GITHUB_TOKEN"], manifest)))
        elif args.command == "sync":
            if not os.environ.get("GITHUB_TOKEN"):
                raise ValueError("GITHUB_TOKEN required for synchronization/publishing")
            previous = restore_previous(args.repo, args.output, args.signing_home, args.fingerprint)
            asset = select_asset(fetch_release())
            if needs_rebuild(asset, previous, recipe_commit(), M13_DTB_SHA256):
                packages, manifest = prepare_packages(args.cache, args.cache / f"packages-{args.revision}", args.revision)
            else:
                age = datetime.now(timezone.utc) - datetime.fromisoformat(previous["metadata_generated_at"])
                if age < timedelta(days=1):
                    print("No upstream/recipe changes; metadata remains current")
                    return 0
                packages = sorted(args.output.glob("*.deb"))
                manifest = dict(previous, metadata_only=True)
            build_repository(packages, args.output, args.signing_home, args.fingerprint, manifest)
            published = json.loads((args.output / "build-manifest.json").read_text())
            print(json.dumps(publish_release(args.repo, args.output, os.environ["GITHUB_TOKEN"], published)))
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError, KeyError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
