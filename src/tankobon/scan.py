from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .model import Chapter, Issue, Page
from .naming import natural_key, parse_name, volume_from_dir

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
ARCHIVE_EXTS = {".cbz", ".zip"}
IGNORED_FILES = {"thumbs.db", "desktop.ini", ".ds_store", "comicinfo.xml"}


@dataclass
class ScanResult:
    chapters: list[Chapter] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)


def scan(root: Path, regex: re.Pattern, max_depth: int = 3, exclude: tuple[Path, ...] = ()) -> ScanResult:
    """Find chapters under root.

    A folder or .cbz/.zip whose name matches the pattern is a chapter. Other
    folders are searched up to max_depth levels; a folder named like "Vol.03"
    gives its volume to unlabelled chapters inside it.
    """
    result = ScanResult()
    excluded = {p.resolve() for p in exclude}
    _walk(root, root, regex, None, 0, max_depth, excluded, result)
    result.chapters.sort(key=lambda c: (c.number, natural_key(c.name)))
    return result


def _walk(root, folder, regex, inherited_volume, depth, max_depth, excluded, result) -> int:
    found = 0
    for entry in sorted(folder.iterdir(), key=lambda p: natural_key(p.name)):
        if entry.name.startswith(".") or (excluded and entry.resolve() in excluded):
            continue
        rel = entry.relative_to(root).as_posix()
        if entry.is_dir():
            parsed = parse_name(entry.name, regex)
            if parsed:
                result.chapters.append(_chapter(entry, parsed, inherited_volume, _folder_pages(entry, result)))
                found += 1
                continue
            sub = 0
            if depth < max_depth:
                volume = volume_from_dir(entry.name)
                sub = _walk(root, entry, regex, volume if volume is not None else inherited_volume,
                            depth + 1, max_depth, excluded, result)
            if not sub:
                result.skipped.append(rel)
            found += sub
        elif entry.is_file() and entry.suffix.lower() in ARCHIVE_EXTS:
            parsed = parse_name(entry.stem, regex)
            if not parsed:
                continue
            pages = _archive_pages(entry, result)
            if pages is not None:
                result.chapters.append(_chapter(entry, parsed, inherited_volume, pages))
                found += 1
    return found


def _chapter(path, parsed, inherited_volume, pages) -> Chapter:
    return Chapter(
        path=path,
        number=parsed.chapter,
        volume=parsed.volume if parsed.volume is not None else inherited_volume,
        title=parsed.title,
        language=parsed.language,
        group=parsed.group,
        pages=pages,
    )


def _is_ignored(name: str) -> bool:
    return name.startswith(".") or name.lower() in IGNORED_FILES


def _page_sort_key(rel: str) -> list:
    return [natural_key(part) for part in PurePosixPath(rel).parts]


def _folder_pages(folder: Path, result: ScanResult) -> list[Page]:
    pages = []
    for f in folder.rglob("*"):
        if not f.is_file() or _is_ignored(f.name):
            continue
        rel = f.relative_to(folder).as_posix()
        if f.suffix.lower() in IMAGE_EXTS:
            pages.append(Page(f, rel, f.stat().st_size))
        else:
            result.issues.append(Issue("non-image", f"skipped non-image file {folder.name}/{rel}"))
    pages.sort(key=lambda p: _page_sort_key(p.rel))
    return pages


def _archive_pages(archive: Path, result: ScanResult) -> list[Page] | None:
    try:
        with zipfile.ZipFile(archive) as z:
            infos = z.infolist()
    except (zipfile.BadZipFile, OSError) as e:
        result.issues.append(Issue("unreadable", f"cannot read {archive.name}: {e}"))
        return None
    pages = []
    for info in infos:
        member = PurePosixPath(info.filename)
        if info.is_dir() or member.parts[0] == "__MACOSX" or _is_ignored(member.name):
            continue
        if member.suffix.lower() in IMAGE_EXTS:
            pages.append(Page(archive, info.filename, info.file_size, in_archive=True))
        else:
            result.issues.append(Issue("non-image", f"skipped non-image file {archive.name}:{info.filename}"))
    pages.sort(key=lambda p: _page_sort_key(p.rel))
    return pages
