"""Decide which chapters go into which output file."""
from __future__ import annotations

import sys
from bisect import bisect_right
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .model import Bundle, Chapter, Issue
from .naming import ch_label, vol_label

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

TRAILING_CHOICES = ("last", "new", "skip")
PER_CHOICES = ("volume", "chapter", "all")


class PlanError(ValueError):
    pass


@dataclass(frozen=True)
class Override:
    low: Decimal
    high: Decimal
    volume: int

    def matches(self, number: Decimal) -> bool:
        return self.low <= number <= self.high


def parse_override(chapters: str, volume) -> Override:
    """Parse "93-95" or "67.5" plus a volume number."""
    if isinstance(volume, bool) or not isinstance(volume, int):
        try:
            volume = int(str(volume).strip())
        except ValueError:
            raise PlanError(f"volume for {chapters!r} must be a whole number, got {volume!r}") from None
    low, sep, high = chapters.strip().partition("-")
    try:
        lo = Decimal(low.strip())
        hi = Decimal(high.strip()) if sep else lo
    except InvalidOperation:
        raise PlanError(f"bad chapter range {chapters!r}, expected e.g. 93 or 93-95 or 67.5") from None
    if hi < lo:
        raise PlanError(f"bad chapter range {chapters!r}: end is before start")
    return Override(lo, hi, volume)


def parse_assign(arg: str) -> Override:
    """Parse a command-line "93-95=21"."""
    chapters, sep, volume = arg.partition("=")
    if not sep:
        raise PlanError(f"bad assignment {arg!r}, expected CHAPTERS=VOLUME, e.g. 93-95=21")
    return parse_override(chapters, volume)


def load_overrides(path: Path) -> list[Override]:
    """Read a volumes.toml of `93-95 = 21` lines.

    TOML reads an unquoted `67.5 = 17` as a nested table, so nested keys are
    joined back with dots.
    """
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as e:
        raise PlanError(f"cannot read {path}: {e}") from None
    except tomllib.TOMLDecodeError as e:
        raise PlanError(f"{path}: {e}") from None
    return [parse_override(key, value) for key, value in _flatten(data)]


def _flatten(table: dict, prefix: str = ""):
    for key, value in table.items():
        full = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            yield from _flatten(value, full)
        else:
            yield full, value


def apply_overrides(chapters: list[Chapter], overrides: list[Override]) -> None:
    for c in chapters:
        for o in overrides:
            if o.matches(c.number):
                c.volume = o.volume
                c.overridden = True
                c.guessed = False


def assign_unlabelled(chapters: list[Chapter], trailing: str = "last") -> tuple[list[Chapter], list[Issue]]:
    """Give every chapter without a volume a guessed one, from the labelled chapters around it.

    A chapter goes in the volume of the nearest labelled chapter below it by
    number (the first volume if it comes before all of them). Chapters after the
    last labelled one go in the last volume ("last"), a new volume ("new"), or
    are left out ("skip"). Returns the chapters to keep and one issue per guess.
    """
    if trailing not in TRAILING_CHOICES:
        raise PlanError(f"trailing must be one of {', '.join(TRAILING_CHOICES)}")
    labelled = [c for c in chapters if c.volume is not None]
    if not labelled:
        return chapters, []
    nums = [c.number for c in labelled]
    last_vol = max(c.volume for c in labelled)
    kept, issues = [], []
    for c in chapters:
        if c.volume is not None:
            kept.append(c)
            continue
        if c.number > nums[-1]:
            if trailing == "skip":
                issues.append(Issue("skipped", f"left out (after the last volume): {c.name}", c))
                continue
            c.volume = last_vol + 1 if trailing == "new" else last_vol
        else:
            i = bisect_right(nums, c.number)
            c.volume = labelled[max(i - 1, 0)].volume
        c.guessed = True
        kept.append(c)
        issues.append(Issue("guessed", f"guessed {vol_label(c.volume)}: {c.name}", c))
    return kept, issues


def check_chapters(chapters: list[Chapter], short: float = 0.6) -> list[Issue]:
    """Flag empty chapters, whole-number chapters well under the median length, gaps and duplicates.

    Decimal chapters (26.5, 61.1) are extras and often short on purpose, so
    they are left out of the short check and the median.
    """
    issues = []
    counts = sorted(len(c.pages) for c in chapters if c.pages and not c.is_extra)
    median = counts[len(counts) // 2] if counts else 0
    for c in chapters:
        if not c.pages:
            issues.append(Issue("empty", f"no pages: {c.name}", c))
        elif not c.is_extra and len(c.pages) < median * short:
            issues.append(Issue("short", f"{len(c.pages)} pages (median {median}): {c.name}", c))
    seen = {}
    for c in chapters:
        if c.number in seen:
            issues.append(Issue("duplicate", f"Ch.{c.number} appears twice: {seen[c.number].name} and {c.name}", c))
        else:
            seen[c.number] = c
    whole = sorted({int(c.number) for c in chapters})
    for a, b in zip(whole, whole[1:]):
        if b - a > 1:
            missing = f"{a + 1}" if b - a == 2 else f"{a + 1}-{b - 1}"
            issues.append(Issue("gap", f"chapters {missing} missing"))
    return issues


def volume_width(chapters: list[Chapter]) -> int:
    return 3 if max((c.volume or 0 for c in chapters), default=0) > 99 else 2


def group(chapters: list[Chapter], per: str = "volume") -> list[Bundle]:
    chapters = sorted(chapters, key=lambda c: c.number)
    if per == "all":
        return [Bundle("", chapters)] if chapters else []
    if per == "chapter":
        bundles = [Bundle(f"Ch.{ch_label(c.number)}", [c], c.volume, str(c.number)) for c in chapters]
        return _unique_labels(bundles)
    if per != "volume":
        raise PlanError(f"per must be one of {', '.join(PER_CHOICES)}")
    width = volume_width(chapters)
    by_volume: dict[int | None, list[Chapter]] = {}
    for c in chapters:
        by_volume.setdefault(c.volume, []).append(c)
    bundles = []
    for vol in sorted(by_volume, key=lambda v: (v is None, v or 0)):
        chs = by_volume[vol]
        if vol is None:
            bundles.append(Bundle(f"Ch.{ch_label(chs[0].number)}-{ch_label(chs[-1].number)}", chs))
        else:
            bundles.append(Bundle(vol_label(vol, width), chs, vol, str(vol)))
    return bundles


def merge(bundles: list[Bundle], indices: list[int]) -> list[Bundle]:
    indices = sorted(set(indices))
    if len(indices) < 2:
        raise PlanError("pick at least two files to merge")
    _check_indices(bundles, indices)
    parts = [bundles[i] for i in indices]
    chapters = sorted((c for b in parts for c in b.chapters), key=lambda c: c.number)
    volumes = sorted({b.volume for b in parts if b.volume is not None})
    if volumes and len(volumes) == len(parts):
        width = volume_width(chapters)
        contiguous = volumes == list(range(volumes[0], volumes[-1] + 1))
        joiner = "-" if contiguous else "+"
        label = vol_label(volumes[0], width) + joiner + (
            f"{volumes[-1]:0{width}d}" if contiguous else "+".join(f"{v:0{width}d}" for v in volumes[1:]))
    else:
        label = "+".join(b.label for b in parts)
    merged = Bundle(label, chapters, volumes[0] if volumes else None,
                    str(volumes[0]) if volumes else parts[0].number)
    result = [replace(b, chapters=list(b.chapters)) for i, b in enumerate(bundles) if i not in indices[1:]]
    result[indices[0]] = merged
    return _unique_labels(result)


def split(bundles: list[Bundle], index: int, at: Chapter) -> list[Bundle]:
    """Split one file in two; `at` becomes the first chapter of the second file."""
    _check_indices(bundles, [index])
    b = bundles[index]
    if at not in b.chapters:
        raise PlanError(f"Ch.{at.number} is not in {b.label or 'that file'}")
    pos = b.chapters.index(at)
    if pos == 0:
        raise PlanError(f"Ch.{at.number} is already the first chapter of {b.label or 'that file'}")
    first = replace(b, label=f"{b.label} part 1".strip(), chapters=b.chapters[:pos])
    second = replace(b, label=f"{b.label} part 2".strip(), chapters=b.chapters[pos:])
    result = [replace(x, chapters=list(x.chapters)) for x in bundles]
    result[index:index + 1] = [first, second]
    return _unique_labels(result)


def move(bundles: list[Bundle], chapter: Chapter, target: int) -> list[Bundle]:
    """Move one chapter into another file. A file left with no chapters is dropped."""
    _check_indices(bundles, [target])
    source = find_bundle(bundles, chapter)
    if source is None:
        raise PlanError(f"Ch.{chapter.number} is not in the plan")
    if source == target:
        return bundles
    result = [replace(b, chapters=list(b.chapters)) for b in bundles]
    result[source].chapters.remove(chapter)
    result[target].chapters.append(chapter)
    result[target].chapters.sort(key=lambda c: c.number)
    return [b for b in result if b.chapters]


def find_bundle(bundles: list[Bundle], chapter: Chapter) -> int | None:
    for i, b in enumerate(bundles):
        if any(c is chapter for c in b.chapters):
            return i
    return None


def find_chapter(bundles: list[Bundle], number: Decimal) -> Chapter | None:
    for b in bundles:
        for c in b.chapters:
            if c.number == number:
                return c
    return None


def select_volumes(bundles: list[Bundle], volumes: set[int]) -> None:
    for b in bundles:
        b.selected = any(c.volume in volumes for c in b.chapters)


def parse_int_ranges(text: str) -> set[int]:
    """Parse "1-5,8" into {1, 2, 3, 4, 5, 8}."""
    out = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        low, sep, high = part.partition("-")
        try:
            lo, hi = int(low), int(high) if sep else int(low)
        except ValueError:
            raise PlanError(f"bad number list {text!r}, expected e.g. 1-5,8") from None
        if hi < lo:
            raise PlanError(f"bad range {part!r}: end is before start")
        out.update(range(lo, hi + 1))
    return out


def chapter_span(chapters: list[Chapter]) -> str:
    """Summarise chapter numbers, e.g. "1-4, 4.5, 5-8". A guessed volume is marked with *."""
    parts: list[str] = []
    run: list[Chapter] = []

    def flush():
        if not run:
            return
        mark = "*" if any(c.guessed for c in run) else ""
        if len(run) == 1:
            parts.append(f"{run[0].number}{mark}")
        else:
            parts.append(f"{run[0].number}-{run[-1].number}{mark}")
        run.clear()

    for c in chapters:
        if run and (c.is_extra or run[-1].is_extra or c.number != run[-1].number + 1
                    or c.guessed != run[-1].guessed):
            flush()
        run.append(c)
    flush()
    return ", ".join(parts)


def _check_indices(bundles: list[Bundle], indices: list[int]) -> None:
    for i in indices:
        if not 0 <= i < len(bundles):
            raise PlanError(f"no file number {i + 1}")


def _unique_labels(bundles: list[Bundle]) -> list[Bundle]:
    seen: dict[str, int] = {}
    for b in bundles:
        n = seen.get(b.label, 0) + 1
        seen[b.label] = n
        if n > 1:
            b.label = f"{b.label} ({n})"
    return bundles
