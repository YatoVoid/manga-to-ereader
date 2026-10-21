from __future__ import annotations

import argparse
import sys
from decimal import Decimal, InvalidOperation
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from . import plan
from .build import Action, BuildOptions, Manifest, plan_actions, run_build
from .project import InputError, Project, Settings, default_out_dir, is_synced_folder, load_project, series_name

EXIT_OK = 0
EXIT_BUILD_FAILED = 1
EXIT_USAGE = 2
EXIT_NO_CHAPTERS = 3
EXIT_WARNINGS = 4

ACTION_TEXT = {
    "write": "write",
    "rebuild": "rebuild (changed)",
    "overwrite": "overwrite",
    "up-to-date": "up to date",
    "exists": "skip (exists, not ours; use --overwrite)",
    "empty": "skip (no pages)",
}

EPILOG = """\
exit codes: 0 done, 1 a file failed to build, 2 bad arguments or input,
3 no chapters found, 4 warnings with --strict

examples:
  tankobon build "Monster Musume no Iru Nichijou" --series "Monster Musume" --dry-run
  tankobon build ./series --out ./cbz --assign 93-95=21 --comicinfo
  tankobon build ./series --merge 1-3 --only 1-5
  tankobon interactive ./series
"""


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "gui":
            try:
                from .gui import main as gui_main
            except ImportError as e:
                print(f"tankobon: error: {e}. Install the GUI extra: pip install 'manga-to-ereader[gui]'", file=sys.stderr)
                return EXIT_USAGE
            return gui_main(args.folder)
        project, opts = prepare(args)
        if args.command == "interactive":
            from .interactive import run
            return run(project, opts)
        return build(project, opts, dry_run=args.dry_run, strict=args.strict)
    except (InputError, plan.PlanError) as e:
        print(f"tankobon: error: {e}", file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:
        return 130


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tankobon",
        description="Bundle per-chapter manga folders into one .cbz per volume. Source folders are never modified.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_version()}")
    sub = parser.add_subparsers(dest="command", required=True)

    build_p = sub.add_parser("build", help="build .cbz files (the automatic mode)", epilog=EPILOG,
                             formatter_class=argparse.RawDescriptionHelpFormatter)
    _add_plan_args(build_p)
    build_p.add_argument("--dry-run", action="store_true", help="print what would be written, write nothing")
    build_p.add_argument("--strict", action="store_true", help="exit 4 without writing if there are any warnings")

    inter_p = sub.add_parser("interactive", help="review and edit the plan in a text menu before building")
    _add_plan_args(inter_p)

    gui_p = sub.add_parser("gui", help="open the desktop window (needs the gui extra)")
    gui_p.add_argument("folder", type=Path, nargs="?", help="series folder to open")
    return parser


def _add_plan_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("folder", type=Path, help="series folder containing chapter folders or .cbz/.zip chapters")
    p.add_argument("--out", type=Path, help='output folder (default: "<folder> (cbz)" next to the series folder)')
    p.add_argument("--series", help="name used in output files (default: folder name)")
    p.add_argument("--per", choices=plan.PER_CHOICES, default="volume", help="one file per volume (default), chapter, or all")
    p.add_argument("--trailing", choices=plan.TRAILING_CHOICES, default="last",
                   help="unlabelled chapters after the last volume: add to it (default), make a new volume, or leave out")
    p.add_argument("--assign", action="append", default=[], metavar="CH=VOL",
                   help="put chapters in a volume, e.g. 93-95=21 or 67.5=17 (repeatable, beats volumes.toml)")
    p.add_argument("--overrides", type=Path, metavar="FILE", help="chapter-to-volume file (default: volumes.toml in the folder)")
    p.add_argument("--merge", action="append", default=[], metavar="VOLS", help="merge volumes into one file, e.g. 1-3 (repeatable)")
    p.add_argument("--split", action="append", default=[], metavar="CH", help="start a new file at this chapter (repeatable)")
    p.add_argument("--only", metavar="VOLS", help="build only these volumes, e.g. 1-5,8")
    p.add_argument("--pattern", help="regex for chapter names, with named groups ch and optionally vol")
    p.add_argument("--depth", type=int, default=3, help="how deep to look for chapter folders (default 3)")
    p.add_argument("--comicinfo", action="store_true", help="add ComicInfo.xml (series, volume, pages, groups)")
    p.add_argument("--compress", action="store_true", help="deflate pages (images barely shrink; off by default)")
    p.add_argument("--overwrite", action="store_true", help="replace existing .cbz files this tool did not write, and rebuild up-to-date ones")
    p.add_argument("--short", type=float, default=0.6, metavar="FRACTION",
                   help="warn when a chapter has fewer pages than this fraction of the median (default 0.6)")


def prepare(args) -> tuple[Project, BuildOptions]:
    root: Path = args.folder
    series = series_name(root, args.series)
    out = args.out or default_out_dir(root)
    settings = Settings(
        pattern=args.pattern,
        trailing=args.trailing,
        per=args.per,
        short=args.short,
        overrides_file=args.overrides,
        assign=[plan.parse_assign(a) for a in args.assign],
        max_depth=args.depth,
    )
    if args.overrides and not args.overrides.is_file():
        raise InputError(f"overrides file not found: {args.overrides}")
    project = load_project(root, settings, exclude=(out,))

    bundles = project.bundles
    for spec in args.merge:
        volumes = plan.parse_int_ranges(spec)
        indices = [i for i, b in enumerate(bundles) if b.volume in volumes]
        if len(indices) < 2:
            raise InputError(f"--merge {spec}: fewer than two of those volumes are in the plan")
        bundles = plan.merge(bundles, indices)
    for spec in args.split:
        try:
            number = Decimal(spec)
        except InvalidOperation:
            raise InputError(f"--split {spec}: not a chapter number") from None
        chapter = plan.find_chapter(bundles, number)
        if chapter is None:
            raise InputError(f"--split {spec}: no such chapter")
        bundles = plan.split(bundles, plan.find_bundle(bundles, chapter), chapter)
    if args.only:
        plan.select_volumes(bundles, plan.parse_int_ranges(args.only))
    project.bundles = bundles
    return project, BuildOptions(out, series, args.comicinfo, args.compress, args.overwrite)


def print_issues(project: Project, file=sys.stderr) -> None:
    if project.overrides_used:
        print(f"using overrides from {project.overrides_used}", file=file)
    for name in project.skipped:
        print(f"warning: skipped folder (no chapter number): {name}", file=file)
    for issue in project.issues:
        print(f"warning: {issue.message}", file=file)


def format_action(action: Action) -> str:
    b = action.bundle
    return f"{ACTION_TEXT[action.kind]:<18} {action.target.name}  {b.page_count} pages  [Ch.{plan.chapter_span(b.chapters)}]"


def build(project: Project, opts: BuildOptions, dry_run: bool = False, strict: bool = False) -> int:
    print_issues(project)
    if not project.chapters:
        print(f"tankobon: no chapters found in {project.root}", file=sys.stderr)
        return EXIT_NO_CHAPTERS
    manifest = Manifest(opts.out_dir)
    actions = plan_actions(project.bundles, opts, manifest)
    if dry_run:
        for a in actions:
            print(format_action(a))
        print(f"dry run: {sum(a.writes for a in actions)} of {len(actions)} files would be written to {opts.out_dir}"
              " (* = volume guessed from chapter number)")
        return EXIT_WARNINGS if strict and (project.issues or project.skipped) else EXIT_OK
    if strict and (project.issues or project.skipped):
        print("tankobon: warnings found and --strict given; nothing written", file=sys.stderr)
        return EXIT_WARNINGS
    if any(a.writes for a in actions) and is_synced_folder(opts.out_dir):
        print(f"warning: {opts.out_dir} looks like a OneDrive folder; every file written will be uploaded", file=sys.stderr)
    for a in actions:
        if not a.writes:
            print(format_action(a))
    report = run_build(actions, opts, manifest, on_progress=lambda msg: print(msg, file=sys.stderr))
    for action, pages in report.written:
        size = action.target.stat().st_size / 1e6
        print(f"wrote {action.target.name}: {pages} pages, {size:.1f} MB [Ch.{plan.chapter_span(action.bundle.chapters)}]")
    for action, error in report.failed:
        print(f"tankobon: failed {action.target.name}: {error}", file=sys.stderr)
    print(f"done: {len(report.written)} files, {report.pages} pages written to {opts.out_dir}"
          " (* = volume guessed from chapter number)")
    return EXIT_BUILD_FAILED if report.failed else EXIT_OK


def _version() -> str:
    try:
        return version("manga-to-ereader")
    except PackageNotFoundError:
        return "unknown"


if __name__ == "__main__":
    sys.exit(main())
