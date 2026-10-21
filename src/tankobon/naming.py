"""Folder-name parsing and output-name rules. Every naming pattern lives here."""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

# Matches "Vol.01 Ch.0001", "Ch.0093", "Volume 1 Chapter 3", "v01 c003", "c003".
# Must define a "ch" group; "vol" is optional.
DEFAULT_PATTERN = (
    r"^(?:v(?:ol(?:ume)?)?\.?\s*(?P<vol>\d+)[\s._-]*)?"
    r"(?:ch(?:apter)?|c)\.?\s*(?P<ch>\d+(?:\.\d+)?)"
)

# A folder that only names a volume, e.g. "Vol.03" or "Volume 3 - Title", holding chapter folders.
VOLUME_DIR_PATTERN = re.compile(r"^v(?:ol(?:ume)?)?\.?\s*(?P<vol>\d+)(?!\d)", re.IGNORECASE)

_LANGUAGE = re.compile(r"\((?P<lang>[a-z]{2,3}(?:-[a-z]{2,4})?)\)", re.IGNORECASE)
_GROUP = re.compile(r"\[(?P<group>[^\]]+)\]")
_TITLE = re.compile(r"^\s*-\s*(?P<title>[^(\[]*?)\s*(?=[(\[]|$)")

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)}


class PatternError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedName:
    chapter: Decimal
    volume: int | None
    title: str = ""
    language: str = ""
    group: str = ""


def compile_pattern(pattern: str | None = None) -> re.Pattern:
    try:
        regex = re.compile(pattern or DEFAULT_PATTERN, re.IGNORECASE)
    except re.error as e:
        raise PatternError(f"invalid pattern: {e}") from None
    if "ch" not in regex.groupindex:
        raise PatternError("pattern must have a named group 'ch', e.g. (?P<ch>\\d+)")
    return regex


def parse_name(name: str, regex: re.Pattern) -> ParsedName | None:
    m = regex.search(name)
    if not m:
        return None
    vol = m.groupdict().get("vol")
    rest = name[m.end():]
    title = _TITLE.match(rest)
    groups = _GROUP.findall(rest)
    lang = _LANGUAGE.search(rest)
    return ParsedName(
        chapter=Decimal(m["ch"]),
        volume=int(vol) if vol else None,
        title=title["title"] if title else "",
        language=lang["lang"].lower() if lang else "",
        group=groups[-1].strip() if groups else "",
    )


def volume_from_dir(name: str) -> int | None:
    m = VOLUME_DIR_PATTERN.match(name)
    return int(m["vol"]) if m else None


def natural_key(name: str) -> list:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def ch_label(n: Decimal) -> str:
    whole, _, frac = str(n).partition(".")
    return whole.zfill(4) + ("." + frac if frac else "")


def vol_label(volume: int, width: int = 2) -> str:
    return f"Vol.{volume:0{width}d}"


def safe_filename(name: str) -> str:
    cleaned = _INVALID_FILENAME_CHARS.sub("", name).strip().rstrip(". ")
    if cleaned.split(".")[0].upper() in _WINDOWS_RESERVED:
        cleaned = "_" + cleaned
    return cleaned
