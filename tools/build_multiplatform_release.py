#!/usr/bin/env python3
"""Build a portable source release for Windows, macOS, and Linux."""

from __future__ import annotations

import argparse
import hashlib
import re
import zipfile
from pathlib import Path
from typing import Iterable


PYTHON_REQUIREMENT = "Python 3.9 or later with Tkinter"
ARCHIVE_PREFIX = "SubtitleUniverseSpellcheck"

RELEASE_FILES = (
    "README.md",
    "LICENSE",
    "app/__init__.py",
    "app/subtitle_cleanup.py",
    "app/subtitle_gui.py",
    "SubtitleUniverseSpellcheck.pyw",
    "docs/USER_GUIDE.md",
    "dictionaries/base/american_words.txt",
    "dictionaries/base/british_words.txt",
    "dictionaries/base/README.md",
    "dictionaries/base/SCOWL-COPYRIGHT.txt",
)


def release_manifest(project_root: Path) -> list[tuple[Path, Path]]:
    """Return the explicit public-runtime allowlist for a source release."""
    root = project_root.resolve()
    return [(root / relative, Path(relative)) for relative in RELEASE_FILES]


def read_version(project_root: Path) -> str:
    engine = project_root.resolve() / "app" / "subtitle_cleanup.py"
    match = re.search(
        r'^SCRIPT_VERSION\s*=\s*["\']([^"\']+)["\']',
        engine.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    if match is None:
        raise RuntimeError(f"Could not read SCRIPT_VERSION from {engine}")
    return match.group(1)


def validate_manifest(manifest: Iterable[tuple[Path, Path]]) -> None:
    missing = [str(source) for source, _destination in manifest if not source.is_file()]
    if missing:
        raise FileNotFoundError("Release input files are missing:\n- " + "\n- ".join(missing))


def validate_archive(archive_path: Path, expected_members: set[str]) -> None:
    """Fail the build if the completed archive is corrupt or has drifted."""
    with zipfile.ZipFile(archive_path) as archive:
        corrupt_member = archive.testzip()
        if corrupt_member is not None:
            raise RuntimeError(f"Release archive contains corrupt data: {corrupt_member}")
        actual_members = {
            name for name in archive.namelist() if name and not name.endswith("/")
        }
    if actual_members != expected_members:
        missing = sorted(expected_members - actual_members)
        unexpected = sorted(actual_members - expected_members)
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unexpected:
            details.append("unexpected: " + ", ".join(unexpected))
        raise RuntimeError("Release archive content drift: " + "; ".join(details))


def build_source_release(
    *,
    project_root: Path,
    output_directory: Path,
) -> tuple[Path, Path]:
    """Create the universal source ZIP and its SHA-256 checksum."""
    root = project_root.resolve()
    manifest = release_manifest(root)
    validate_manifest(manifest)
    version = read_version(root)
    archive_root = f"{ARCHIVE_PREFIX}-{version}"
    destination = output_directory.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    archive_path = destination / f"{archive_root}-source.zip"
    checksum_path = archive_path.with_suffix(archive_path.suffix + ".sha256")

    with zipfile.ZipFile(
        archive_path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for source, relative_destination in manifest:
            archive.write(source, (Path(archive_root) / relative_destination).as_posix())

    validate_archive(
        archive_path,
        {
            (Path(archive_root) / relative_destination).as_posix()
            for _source, relative_destination in manifest
        },
    )

    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    with checksum_path.open("w", encoding="ascii", newline="\n") as checksum_file:
        checksum_file.write(f"{digest}  {archive_path.name}\n")
    return archive_path, checksum_path


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build the Python 3.9+ source release shared by Windows, macOS, and Linux."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="artifact directory (default: <project>/artifacts)",
    )
    return parser


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    arguments = build_argument_parser().parse_args()
    output_directory = arguments.output_dir or project_root / "artifacts"
    archive_path, checksum_path = build_source_release(
        project_root=project_root,
        output_directory=output_directory,
    )
    print(f"Universal source release created for {PYTHON_REQUIREMENT}:")
    print(f"  {archive_path}")
    print(f"  {checksum_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
