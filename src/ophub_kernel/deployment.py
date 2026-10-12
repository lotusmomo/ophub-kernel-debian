import ipaddress
import re
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
