"""
core/updater.py — Check GitHub Releases for a newer AccessDR and fetch it.

Pure logic (no wx): query the GitHub Releases API, compare the newest
applicable release against the running version using PEP 440 ordering, and
download the Windows installer asset.  The UI layer (ui/dialogs/update_dialog)
presents the result and drives the download/install.

Only the installer build should act on the result — running from source has
no installer to replace (callers gate on config.paths.is_frozen()).
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import urllib.request
from typing import Callable, List, Optional

from packaging.version import InvalidVersion, Version, parse

logger = logging.getLogger(__name__)

# GitHub repository and the installer asset naming used by build.yml.
REPO = "ragb/accessdr"
RELEASES_URL = f"https://api.github.com/repos/{REPO}/releases?per_page=20"
_ASSET_RE = re.compile(r"AccessDR-.*-setup\.exe$", re.IGNORECASE)
_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "AccessDR-updater",
}


class UpdateInfo:
    """A newer release that can be installed."""

    def __init__(
        self, version: str, tag: str, name: str, body: str,
        asset_url: str, asset_name: str,
    ) -> None:
        self.version = version          # normalized, e.g. "0.7.0"
        self.tag = tag                  # raw tag, e.g. "v0.7.0"
        self.name = name                # release title
        self.body = body                # changelog / release notes
        self.asset_url = asset_url      # installer download URL
        self.asset_name = asset_name    # installer filename

    def __repr__(self) -> str:
        return f"UpdateInfo({self.tag}, {self.asset_name})"


def _norm(tag: str) -> Version:
    """Parse a release tag (``v0.7.0`` / ``0.7.0``) to a PEP 440 Version."""
    return parse(tag.lstrip("vV"))


def fetch_releases(timeout: float = 10.0) -> List[dict]:
    """Fetch the releases list from the GitHub API (raises on network error)."""
    req = urllib.request.Request(RELEASES_URL, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check_for_update(
    current_version: str,
    include_prereleases: Optional[bool] = None,
    releases: Optional[List[dict]] = None,
) -> Optional[UpdateInfo]:
    """Return an :class:`UpdateInfo` if a newer installable release exists.

    *include_prereleases* defaults to True when the running version is itself a
    pre-release (beta users follow betas), else stable-only.  Pass *releases* to
    bypass the network (used by tests).
    """
    try:
        current = parse(current_version)
    except InvalidVersion:
        logger.warning("unparseable current version: %r", current_version)
        return None

    if include_prereleases is None:
        include_prereleases = current.is_prerelease

    if releases is None:
        releases = fetch_releases()

    best: Optional[UpdateInfo] = None
    best_ver: Optional[Version] = None
    for rel in releases:
        if rel.get("draft"):
            continue
        if rel.get("prerelease") and not include_prereleases:
            continue
        try:
            ver = _norm(rel.get("tag_name", ""))
        except InvalidVersion:
            continue
        asset = next(
            (a for a in rel.get("assets", []) if _ASSET_RE.search(a.get("name", ""))),
            None,
        )
        if asset is None:
            continue
        if best_ver is None or ver > best_ver:
            best_ver = ver
            best = UpdateInfo(
                version=str(ver),
                tag=rel.get("tag_name", ""),
                name=rel.get("name") or rel.get("tag_name", ""),
                body=rel.get("body") or "",
                asset_url=asset.get("browser_download_url", ""),
                asset_name=asset.get("name", ""),
            )

    if best is None or best_ver is None or best_ver <= current:
        return None
    return best


def download_asset(
    url: str,
    dest_dir: Optional[str] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    cancel_cb: Optional[Callable[[], bool]] = None,
    timeout: float = 30.0,
) -> Optional[str]:
    """Download *url* to *dest_dir* (temp by default); return the saved path.

    *progress_cb(done, total)* is called as bytes arrive (total may be 0 if the
    server omits Content-Length).  *cancel_cb* returning True aborts and removes
    the partial file (returns None).
    """
    dest_dir = dest_dir or tempfile.gettempdir()
    name = os.path.basename(url.split("?", 1)[0]) or "AccessDR-setup.exe"
    path = os.path.join(dest_dir, name)
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(path, "wb") as fh:
            while True:
                if cancel_cb is not None and cancel_cb():
                    fh.close()
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                    return None
                chunk = resp.read(65536)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if progress_cb is not None:
                    progress_cb(done, total)
    return path
