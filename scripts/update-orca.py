#!/usr/bin/env python3
"""Update nix-orca to a stable upstream Orca release."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import stat
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

API_ROOT = "https://api.github.com/repos/stablyai/orca/releases"
DOWNLOAD_ROOT = "https://github.com/stablyai/orca/releases/download"
VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")
TAG_RE = re.compile(r"v([0-9]+\.[0-9]+\.[0-9]+)\Z")
DIGEST_RE = re.compile(r"sha256:([0-9a-f]{64})\Z")

SYSTEM_ASSETS = (
    ("x86_64-linux", "orca-linux.AppImage"),
    ("aarch64-linux", "orca-linux-arm64.AppImage"),
    ("aarch64-darwin", "Orca-{version}-arm64-mac.zip"),
)


class UpdateError(Exception):
    """An expected updater failure that should be shown without a traceback."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update package.nix to an Orca stable release."
    )
    parser.add_argument(
        "--version",
        metavar="X",
        help="update to stable version X (for example, 1.4.137); default: latest",
    )
    args = parser.parse_args(argv)
    if args.version is not None and VERSION_RE.fullmatch(args.version) is None:
        parser.error("--version must have the form MAJOR.MINOR.PATCH (without a leading v)")
    return args


def fetch_release(requested_version: str | None) -> dict[str, Any]:
    endpoint = "latest" if requested_version is None else f"tags/v{requested_version}"
    request = urllib.request.Request(
        f"{API_ROOT}/{endpoint}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "nix-orca-update-script",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read()
    except urllib.error.HTTPError as error:
        detail = error.reason
        try:
            error_payload = json.loads(error.read().decode("utf-8"))
            if isinstance(error_payload, dict) and isinstance(error_payload.get("message"), str):
                detail = error_payload["message"]
        except (UnicodeDecodeError, json.JSONDecodeError, OSError):
            pass
        raise UpdateError(f"GitHub API request failed ({error.code}): {detail}") from error
    except urllib.error.URLError as error:
        raise UpdateError(f"GitHub API request failed: {error.reason}") from error
    except TimeoutError as error:
        raise UpdateError("GitHub API request timed out") from error

    try:
        release = json.loads(payload.decode("utf-8"))
    except UnicodeDecodeError as error:
        raise UpdateError("GitHub API returned a response that is not UTF-8") from error
    except json.JSONDecodeError as error:
        raise UpdateError(f"GitHub API returned invalid JSON: {error.msg}") from error
    if not isinstance(release, dict):
        raise UpdateError("GitHub API schema error: release response is not an object")
    return release


def require_bool(release: dict[str, Any], field: str) -> bool:
    value = release.get(field)
    if type(value) is not bool:
        raise UpdateError(f"GitHub API schema error: release.{field} is not a boolean")
    return value


def release_hashes(
    release: dict[str, Any], requested_version: str | None
) -> tuple[str, dict[str, str]]:
    if require_bool(release, "draft"):
        raise UpdateError("refusing to update from a draft release")
    if require_bool(release, "prerelease"):
        raise UpdateError("refusing to update from a prerelease")

    tag = release.get("tag_name")
    if not isinstance(tag, str):
        raise UpdateError("GitHub API schema error: release.tag_name is not a string")
    tag_match = TAG_RE.fullmatch(tag)
    if tag_match is None:
        raise UpdateError(
            f"release tag {tag!r} is not a stable vMAJOR.MINOR.PATCH tag"
        )
    version = tag_match.group(1)
    if requested_version is not None and version != requested_version:
        raise UpdateError(
            f"GitHub API returned tag {tag!r}, expected v{requested_version}"
        )

    assets = release.get("assets")
    if not isinstance(assets, list):
        raise UpdateError("GitHub API schema error: release.assets is not an array")

    assets_by_name: dict[str, list[dict[str, Any]]] = {}
    for index, asset in enumerate(assets):
        if not isinstance(asset, dict):
            raise UpdateError(
                f"GitHub API schema error: release.assets[{index}] is not an object"
            )
        name = asset.get("name")
        if not isinstance(name, str):
            raise UpdateError(
                f"GitHub API schema error: release.assets[{index}].name is not a string"
            )
        assets_by_name.setdefault(name, []).append(asset)

    hashes: dict[str, str] = {}
    for system, asset_template in SYSTEM_ASSETS:
        asset_name = asset_template.format(version=version)
        matching_assets = assets_by_name.get(asset_name, [])
        if not matching_assets:
            raise UpdateError(f"release is missing required asset {asset_name!r}")
        if len(matching_assets) != 1:
            raise UpdateError(f"release contains duplicate asset {asset_name!r}")
        asset = matching_assets[0]

        expected_url = f"{DOWNLOAD_ROOT}/v{version}/{asset_name}"
        actual_url = asset.get("browser_download_url")
        if not isinstance(actual_url, str):
            raise UpdateError(
                f"GitHub API schema error: asset {asset_name!r} has no string download URL"
            )
        if actual_url != expected_url:
            raise UpdateError(
                f"asset {asset_name!r} has unexpected download URL {actual_url!r}; "
                f"expected {expected_url!r}"
            )

        digest = asset.get("digest")
        if not isinstance(digest, str):
            raise UpdateError(
                f"GitHub API schema error: asset {asset_name!r} has no string digest"
            )
        digest_match = DIGEST_RE.fullmatch(digest)
        if digest_match is None:
            raise UpdateError(
                f"asset {asset_name!r} digest must be sha256 followed by 64 lowercase hex digits"
            )
        digest_bytes = bytes.fromhex(digest_match.group(1))
        hashes[system] = "sha256-" + base64.b64encode(digest_bytes).decode("ascii")

    return version, hashes


def replace_exactly_once(
    text: str, pattern: re.Pattern[str], replacement: str, description: str
) -> str:
    updated, count = pattern.subn(lambda match: f"{match.group(1)}{replacement}{match.group(2)}", text)
    if count != 1:
        raise UpdateError(f"expected exactly one {description}, found {count}")
    return updated


def update_package(text: str, version: str, hashes: dict[str, str]) -> str:
    version_pattern = re.compile(
        r'(?m)^([ \t]*version[ \t]*=[ \t]*")[0-9]+\.[0-9]+\.[0-9]+(";[ \t]*(?:#[^\r\n]*)?)(?=\r?$)'
    )
    updated = replace_exactly_once(
        text, version_pattern, version, "package version assignment"
    )

    for system, _asset in SYSTEM_ASSETS:
        block_pattern = re.compile(
            rf"(?ms)^(?P<indent>[ \t]+){re.escape(system)}[ \t]*=[ \t]*\{{[ \t]*(?:#[^\r\n]*)?\r?\n"
            rf"(?P<body>.*?)(?=^(?P=indent)\}};[ \t]*(?:#[^\r\n]*)?\r?$)"
        )
        blocks = list(block_pattern.finditer(updated))
        if len(blocks) != 1:
            raise UpdateError(
                f"expected exactly one {system} source block, found {len(blocks)}"
            )
        block = blocks[0]
        block_text = block.group(0)
        hash_pattern = re.compile(
            r'(?m)^([ \t]*hash[ \t]*=[ \t]*")[^"\r\n]+(";[ \t]*(?:#[^\r\n]*)?)(?=\r?$)'
        )
        new_block = replace_exactly_once(
            block_text, hash_pattern, hashes[system], f"hash in {system} source block"
        )
        updated = updated[: block.start()] + new_block + updated[block.end() :]

    return updated


def read_utf8(path: Path) -> tuple[bytes, str]:
    try:
        original = path.read_bytes()
    except OSError as error:
        raise UpdateError(f"cannot read {path}: {error}") from error
    try:
        return original, original.decode("utf-8")
    except UnicodeDecodeError as error:
        raise UpdateError(f"{path} is not valid UTF-8") from error


def stage_file(path: Path, content: bytes) -> Path:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent
        )
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, mode)
        return temporary
    except OSError as error:
        if "temporary" in locals():
            temporary.unlink(missing_ok=True)
        raise UpdateError(f"cannot stage update for {path}: {error}") from error


def write_atomically(updates: list[tuple[Path, bytes]]) -> None:
    staged: list[tuple[Path, Path]] = []
    try:
        for path, content in updates:
            staged.append((path, stage_file(path, content)))
        for path, temporary in staged:
            os.replace(temporary, path)
    except OSError as error:
        raise UpdateError(f"cannot install update: {error}") from error
    finally:
        for _path, temporary in staged:
            temporary.unlink(missing_ok=True)


def append_github_output(version: str, changed: bool) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    try:
        with open(output_path, "a", encoding="utf-8", newline="\n") as output:
            output.write(f"version={version}\n")
            output.write(f"changed={'true' if changed else 'false'}\n")
    except OSError as error:
        raise UpdateError(f"cannot append to GITHUB_OUTPUT: {error}") from error


def run(args: argparse.Namespace) -> tuple[str, bool]:
    release = fetch_release(args.version)
    version, hashes = release_hashes(release, args.version)

    repository = Path(__file__).resolve().parents[1]
    package_path = repository / "package.nix"
    package_bytes, package_text = read_utf8(package_path)
    new_package = update_package(package_text, version, hashes).encode("utf-8")

    changed = package_bytes != new_package
    if changed:
        write_atomically([(package_path, new_package)])
    append_github_output(version, changed)
    return version, changed


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        version, changed = run(args)
    except UpdateError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if changed:
        print(f"updated Orca to {version}")
    else:
        print(f"Orca {version} is already up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
