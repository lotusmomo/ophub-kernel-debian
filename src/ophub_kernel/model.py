from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass(frozen=True)
class Asset:
    name: str
    version: str
    id: int
    updated_at: str
    url: str
    sha256: str
    size: int

    def fingerprint(self):
        return asdict(self)


@dataclass(frozen=True)
class ValidatedKernel:
    release: str
    boot_dir: Path
    modules_dir: Path
    dtb_dir: Path
    config: dict[str, str]
    m13_dtb: Path
