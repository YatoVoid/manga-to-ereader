from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path, PurePosixPath


@dataclass(frozen=True)
class Page:
    source: Path
    """The image file, or the chapter archive that holds it."""
    rel: str
    """Path relative to the chapter folder, or the member name inside the archive."""
    size: int
    in_archive: bool = False

    @property
    def name(self) -> str:
        return PurePosixPath(self.rel).name


@dataclass(eq=False)
class Chapter:
    path: Path
    number: Decimal
    volume: int | None
    title: str = ""
    language: str = ""
    group: str = ""
    pages: list[Page] = field(default_factory=list)
    guessed: bool = False
    overridden: bool = False

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def is_extra(self) -> bool:
        return self.number != int(self.number)


@dataclass(frozen=True)
class Issue:
    kind: str
    message: str
    chapter: Chapter | None = None


@dataclass
class Bundle:
    """One output file and the chapters that go into it."""

    label: str
    chapters: list[Chapter]
    volume: int | None = None
    number: str | None = None
    selected: bool = True

    @property
    def page_count(self) -> int:
        return sum(len(c.pages) for c in self.chapters)

    def filename(self, series: str) -> str:
        return f"{series} {self.label}".strip() + ".cbz"
