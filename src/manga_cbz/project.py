"""Scan a series folder and turn it into a build plan. Shared by the CLI, interactive mode and the GUI."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from . import plan
from .model import Bundle, Chapter, Issue
from .naming import compile_pattern, safe_filename
from .scan import scan

OVERRIDES_NAME = "volumes.toml"


class InputError(ValueError):
    pass


@dataclass
class Settings:
    pattern: str | None = None
    trailing: str = "last"
    per: str = "volume"
    short: float = 0.6
    overrides_file: Path | None = None
    """None means use volumes.toml in the series folder if there is one."""
    assign: list[plan.Override] = field(default_factory=list)
    max_depth: int = 3


@dataclass
class Project:
    root: Path
    chapters: list[Chapter]
    bundles: list[Bundle]
    issues: list[Issue]
    skipped: list[str]
    overrides_used: Path | None = None


def load_project(root: Path, settings: Settings, exclude: tuple[Path, ...] = ()) -> Project:
    if not root.is_dir():
        raise InputError(f"not a folder: {root}")
    try:
        regex = compile_pattern(settings.pattern)
    except ValueError as e:
        raise InputError(str(e)) from None
    found = scan(root, regex, settings.max_depth, exclude)
    overrides_path = settings.overrides_file
    if overrides_path is None and (root / OVERRIDES_NAME).is_file():
        overrides_path = root / OVERRIDES_NAME
    try:
        overrides = plan.load_overrides(overrides_path) if overrides_path else []
        plan.apply_overrides(found.chapters, overrides + settings.assign)
        chapters, guesses = plan.assign_unlabelled(found.chapters, settings.trailing)
        bundles = plan.group(chapters, settings.per)
    except plan.PlanError as e:
        raise InputError(str(e)) from None
    issues = found.issues + guesses + plan.check_chapters(chapters, settings.short)
    if chapters and all(c.volume is None for c in chapters) and settings.per == "volume":
        issues.append(Issue("no-volumes", "no chapter has a volume label; all chapters go in one file. "
                                          "Use volumes.toml, --assign, or --per chapter"))
    return Project(root, chapters, bundles, issues, found.skipped, overrides_path)


def series_name(root: Path, given: str | None) -> str:
    name = safe_filename(given if given is not None else root.name)
    if not name:
        raise InputError(f"series name {given or root.name!r} has no usable characters")
    return name


def default_out_dir(root: Path) -> Path:
    return root.parent / f"{root.name} (cbz)"


def is_synced_folder(path: Path) -> bool:
    """True if path looks like it is inside OneDrive, where writing GBs of .cbz starts a big upload."""
    resolved = path.resolve()
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        base = os.environ.get(var)
        if base and resolved.is_relative_to(Path(base).resolve()):
            return True
    return any(part.lower().startswith("onedrive") for part in resolved.parts)
