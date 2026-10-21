import zipfile
from pathlib import Path

import pytest

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16


def make_chapter(root: Path, name: str, pages: int = 3, ext: str = ".jpg") -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    for i in range(1, pages + 1):
        (folder / f"{i}{ext}").write_bytes(JPEG + bytes([i % 256]))
    return folder


def make_archive_chapter(root: Path, name: str, pages: int = 3) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    with zipfile.ZipFile(path, "w") as z:
        for i in range(1, pages + 1):
            z.writestr(f"{i}.jpg", JPEG + bytes([i]))
    return path


def snapshot(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): (p.is_dir(), p.stat().st_size if p.is_file() else 0, p.stat().st_mtime_ns)
            for p in root.rglob("*")}


@pytest.fixture
def series(tmp_path) -> Path:
    """Modelled on the real data: a decimal extra, an unlabelled chapter on a volume
    boundary, a short chapter, and unlabelled chapters after the last volume."""
    root = tmp_path / "Test Series"
    make_chapter(root, "Vol.01 Ch.0001 (en) [Group A]", 10)
    make_chapter(root, "Vol.01 Ch.0002 (en) [Group A]", 10)
    make_chapter(root, "Vol.01 Ch.0002.5 - Extra (en) [Group A]", 2)
    make_chapter(root, "Ch.0003 (en) [Group A]", 10)
    make_chapter(root, "Vol.02 Ch.0004 (en) [Group B]", 10)
    make_chapter(root, "Vol.02 Ch.0005 (en) [Group B]", 3)
    make_chapter(root, "Ch.0006 (en) [Group B]", 10)
    make_chapter(root, "Ch.0007 (en) [Group B]", 10)
    return root
