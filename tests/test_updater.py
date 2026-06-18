"""Tests for the GitHub-release update checker (core/updater.py)."""

from core.updater import check_for_update


def _rel(tag, *, prerelease=False, draft=False, with_asset=True, name=None):
    assets = []
    if with_asset:
        ver = tag.lstrip("v")
        assets = [{
            "name": f"AccessDR-{ver}-setup.exe",
            "browser_download_url": f"https://example/{tag}/AccessDR-{ver}-setup.exe",
        }]
    return {
        "tag_name": tag, "name": name or tag, "body": "notes",
        "prerelease": prerelease, "draft": draft, "assets": assets,
    }


def test_detects_newer_stable():
    rels = [_rel("v0.6.0"), _rel("v0.7.0")]
    info = check_for_update("0.6.0", releases=rels)
    assert info is not None
    assert info.version == "0.7.0"
    assert info.asset_name == "AccessDR-0.7.0-setup.exe"
    assert info.asset_url.endswith("setup.exe")


def test_no_update_when_current_is_newest():
    rels = [_rel("v0.6.0"), _rel("v0.7.0")]
    assert check_for_update("0.7.0", releases=rels) is None
    assert check_for_update("1.0.0", releases=rels) is None


def test_prereleases_excluded_for_stable_user():
    rels = [_rel("v0.7.0b2", prerelease=True), _rel("v0.6.0")]
    # Stable user (0.6.0) should not be offered the beta.
    assert check_for_update("0.6.0", releases=rels) is None


def test_prereleases_included_for_beta_user():
    rels = [_rel("v0.7.0b2", prerelease=True), _rel("v0.6.0")]
    info = check_for_update("0.7.0b1", releases=rels)
    assert info is not None and info.version == "0.7.0b2"


def test_stable_beats_older_beta_for_beta_user():
    rels = [_rel("v0.7.0b1", prerelease=True), _rel("v0.7.0")]
    info = check_for_update("0.6.0", releases=rels, include_prereleases=True)
    assert info is not None and info.version == "0.7.0"


def test_releases_without_installer_asset_are_ignored():
    rels = [_rel("v0.7.0", with_asset=False), _rel("v0.6.5")]
    info = check_for_update("0.6.0", releases=rels)
    assert info is not None and info.version == "0.6.5"


def test_drafts_ignored():
    rels = [_rel("v0.9.0", draft=True), _rel("v0.7.0")]
    info = check_for_update("0.6.0", releases=rels)
    assert info.version == "0.7.0"


def test_unparseable_current_version_returns_none():
    assert check_for_update("not-a-version", releases=[_rel("v9.9.9")]) is None


def test_explicit_include_prereleases_false():
    rels = [_rel("v0.8.0b1", prerelease=True)]
    assert check_for_update("0.7.0b1", releases=rels, include_prereleases=False) is None
