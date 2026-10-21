"""Write .cbz files, with optional ComicInfo.xml, and track what was built."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from xml.etree import ElementTree as ET

from .model import Bundle
from .naming import ch_label

MANIFEST_NAME = ".tankobon.json"
WRITE_KINDS = {"write", "rebuild", "overwrite"}


class BuildError(RuntimeError):
    pass


@dataclass
class BuildOptions:
    out_dir: Path
    series: str
    comicinfo: bool = False
    compress: bool = False
    overwrite: bool = False


@dataclass
class Action:
    bundle: Bundle
    target: Path
    kind: str
    """write, rebuild (changed since last build), overwrite, up-to-date, exists (skipped) or empty."""
    fingerprint: str

    @property
    def writes(self) -> bool:
        return self.kind in WRITE_KINDS


@dataclass
class BuildReport:
    written: list[tuple[Action, int]] = field(default_factory=list)
    failed: list[tuple[Action, str]] = field(default_factory=list)

    @property
    def pages(self) -> int:
        return sum(n for _, n in self.written)


class Manifest:
    """Records the fingerprint of every file this tool wrote to an output folder.

    A file whose fingerprint still matches is up to date and not rebuilt. A file
    that exists but is not in the manifest is not ours, so it is only replaced
    with --overwrite.
    """

    def __init__(self, out_dir: Path):
        self.path = out_dir / MANIFEST_NAME
        self.files: dict[str, dict] = {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("files"), dict):
                self.files = data["files"]
        except (OSError, ValueError):
            pass

    def fingerprint_of(self, name: str) -> str | None:
        entry = self.files.get(name)
        return entry.get("fingerprint") if isinstance(entry, dict) else None

    def record(self, action: Action, pages: int) -> None:
        self.files[action.target.name] = {
            "fingerprint": action.fingerprint,
            "pages": pages,
            "chapters": [str(c.number) for c in action.bundle.chapters],
        }

    def save(self) -> None:
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps({"version": 1, "files": self.files}, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)


def fingerprint(bundle: Bundle, opts: BuildOptions) -> str:
    data = {
        "series": opts.series,
        "label": bundle.label,
        "comicinfo": opts.comicinfo,
        "chapters": [
            [c.name, str(c.number), [[p.rel, p.size] for p in c.pages]] for c in bundle.chapters
        ],
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def plan_actions(bundles: list[Bundle], opts: BuildOptions, manifest: Manifest) -> list[Action]:
    actions = []
    for b in bundles:
        if not b.selected:
            continue
        target = opts.out_dir / b.filename(opts.series)
        fp = fingerprint(b, opts)
        if b.page_count == 0:
            kind = "empty"
        elif not target.exists():
            kind = "write"
        elif opts.overwrite:
            kind = "overwrite"
        elif manifest.fingerprint_of(target.name) == fp:
            kind = "up-to-date"
        elif manifest.fingerprint_of(target.name) is not None:
            kind = "rebuild"
        else:
            kind = "exists"
        actions.append(Action(b, target, kind, fp))
    return actions


def run_build(actions: list[Action], opts: BuildOptions, manifest: Manifest,
              on_progress: Callable[[str], None] = lambda _msg: None) -> BuildReport:
    """Build every writing action. One failed file does not stop the others."""
    report = BuildReport()
    todo = [a for a in actions if a.writes]
    if todo:
        opts.out_dir.mkdir(parents=True, exist_ok=True)
    for n, action in enumerate(todo, 1):
        on_progress(f"[{n}/{len(todo)}] {action.target.name}")
        try:
            pages = write_cbz(action.bundle, action.target, opts)
        except (OSError, zipfile.BadZipFile, BuildError) as e:
            report.failed.append((action, str(e)))
            continue
        report.written.append((action, pages))
        manifest.record(action, pages)
        manifest.save()
    return report


def write_cbz(bundle: Bundle, target: Path, opts: BuildOptions) -> int:
    """Write a .cbz next to target, verify it, then move it into place. Returns the page count."""
    tmp = target.with_name(target.name + ".tmp")
    method = zipfile.ZIP_DEFLATED if opts.compress else zipfile.ZIP_STORED
    pages = [(c, p) for c in bundle.chapters for p in c.pages]
    width = max(4, len(str(len(pages))))
    archives: dict[Path, zipfile.ZipFile] = {}
    try:
        # strict_timestamps=False: images with pre-1980 mtimes would otherwise abort the write.
        with zipfile.ZipFile(tmp, "w", method, strict_timestamps=False) as z:
            if opts.comicinfo:
                z.writestr("ComicInfo.xml", comicinfo_xml(bundle, opts.series, len(pages)))
            for i, (chapter, page) in enumerate(pages, 1):
                arcname = f"{i:0{width}d}_Ch{ch_label(chapter.number)}_{page.name}"
                if not page.in_archive:
                    z.write(page.source, arcname)
                    continue
                src = archives.get(page.source)
                if src is None:
                    src = archives[page.source] = zipfile.ZipFile(page.source)
                with src.open(page.rel) as fin, z.open(arcname, "w") as fout:
                    shutil.copyfileobj(fin, fout, 1 << 20)
        _verify(tmp, len(pages) + (1 if opts.comicinfo else 0))
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    finally:
        for a in archives.values():
            a.close()
    return len(pages)


def _verify(path: Path, expected: int) -> None:
    with zipfile.ZipFile(path) as z:
        count = len(z.namelist())
        if count != expected:
            raise BuildError(f"verify failed for {path.name}: {count} entries, expected {expected}")
        bad = z.testzip()
        if bad is not None:
            raise BuildError(f"verify failed for {path.name}: bad CRC in {bad}")


def comicinfo_xml(bundle: Bundle, series: str, page_count: int) -> bytes:
    root = ET.Element("ComicInfo", {
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xmlns:xsd": "http://www.w3.org/2001/XMLSchema",
    })

    def add(tag: str, value) -> None:
        if value not in (None, ""):
            ET.SubElement(root, tag).text = str(value)

    languages = {c.language for c in bundle.chapters if c.language}
    groups = list(dict.fromkeys(c.group for c in bundle.chapters if c.group))
    add("Title", bundle.label or series)
    add("Series", series)
    add("Number", bundle.number)
    add("Volume", bundle.volume)
    add("Notes", "Chapters: " + ", ".join(str(c.number) for c in bundle.chapters))
    add("PageCount", page_count)
    add("LanguageISO", languages.pop() if len(languages) == 1 else None)
    add("ScanInformation", ", ".join(groups))
    add("Manga", "Yes")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
