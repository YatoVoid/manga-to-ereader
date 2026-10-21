"""Text menu for reviewing and editing the plan before writing. Plain line input, so it works over SSH and in any terminal."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Callable

from . import plan
from .build import BuildOptions, Manifest, plan_actions, run_build
from .cli import ACTION_TEXT, EXIT_BUILD_FAILED, EXIT_NO_CHAPTERS, EXIT_OK, print_issues
from .model import Bundle
from .project import Project, is_synced_folder

HELP = """\
commands (file numbers come from the list; ranges like 3-5 or 3,5 work):
  l                  list files
  s N                show the chapters in file N
  t N                include or exclude files from the build
  a / n              include all / none
  m N                merge files into one, e.g. m 1-3
  p CH               split: start a new file at chapter CH
  v CH N             move chapter CH into file N
  u                  undo the last change
  b                  build the included files (asks first)
  q                  quit without building
"""

FLAG_KINDS = ("short", "empty", "duplicate")


def run(project: Project, opts: BuildOptions,
        ask: Callable[[str], str] = input, say: Callable[[str], None] = print) -> int:
    print_issues(project)
    if not project.chapters:
        say(f"no chapters found in {project.root}")
        return EXIT_NO_CHAPTERS
    menu = Menu(project, opts, say)
    menu.show_list()
    say("type ? for commands")
    while True:
        try:
            line = ask("> ").strip()
        except EOFError:
            return EXIT_OK
        if not line:
            continue
        cmd, _, rest = line.partition(" ")
        cmd = cmd.lower()
        if cmd in ("q", "quit", "exit"):
            return EXIT_OK
        if cmd in ("b", "build"):
            code = menu.build(ask)
            if code is not None:
                return code
            continue
        handler = menu.commands.get(cmd)
        if handler is None:
            say(f"unknown command {cmd!r}; type ? for commands")
            continue
        try:
            handler(rest.strip())
        except (plan.PlanError, ValueError) as e:
            say(f"error: {e}")


class Menu:
    def __init__(self, project: Project, opts: BuildOptions, say: Callable[[str], None]):
        self.project = project
        self.opts = opts
        self.say = say
        self.history: list[list[Bundle]] = []
        flagged = {}
        for issue in project.issues:
            if issue.chapter is not None and issue.kind in FLAG_KINDS:
                flagged.setdefault(id(issue.chapter), []).append(issue.kind)
        self.flags = flagged
        self.commands = {
            "?": lambda _: say(HELP), "h": lambda _: say(HELP), "help": lambda _: say(HELP),
            "l": lambda _: self.show_list(), "list": lambda _: self.show_list(),
            "s": self.show_file, "show": self.show_file,
            "t": self.toggle, "toggle": self.toggle,
            "a": lambda _: self.set_all(True), "all": lambda _: self.set_all(True),
            "n": lambda _: self.set_all(False), "none": lambda _: self.set_all(False),
            "m": self.merge, "merge": self.merge,
            "p": self.split, "split": self.split,
            "v": self.move, "move": self.move,
            "u": self.undo, "undo": self.undo,
        }

    @property
    def bundles(self) -> list[Bundle]:
        return self.project.bundles

    def show_list(self) -> None:
        manifest = Manifest(self.opts.out_dir)
        status = {id(a.bundle): a.kind for a in plan_actions(self.bundles, self.opts, manifest)}
        self.say(f"{self.opts.series}: {len(self.project.chapters)} chapters, {len(self.bundles)} files, out: {self.opts.out_dir}")
        for i, b in enumerate(self.bundles, 1):
            mark = "x" if b.selected else " "
            kind = ACTION_TEXT[status[id(b)]].split(" (")[0] if b.selected else "-"
            flags = sorted({k for c in b.chapters for k in self.flags.get(id(c), [])})
            note = f"  !{','.join(flags)}" if flags else ""
            self.say(f"{i:>3} [{mark}] {kind:<10} {b.filename(self.opts.series)}  {b.page_count}p  "
                     f"Ch.{plan.chapter_span(b.chapters)}{note}")

    def show_file(self, arg: str) -> None:
        (index,) = self._file_numbers(arg, exactly_one=True)
        b = self.bundles[index]
        self.say(b.filename(self.opts.series))
        for c in b.chapters:
            vol = "-" if c.volume is None else f"{c.volume}{'*' if c.guessed else ''}"
            flags = ",".join(self.flags.get(id(c), []))
            self.say(f"  Ch.{c.number:<8} vol {vol:<4} {len(c.pages):>4}p  {flags:<10} {c.name}")

    def toggle(self, arg: str) -> None:
        for i in self._file_numbers(arg):
            self.bundles[i].selected = not self.bundles[i].selected
        self.show_list()

    def set_all(self, value: bool) -> None:
        for b in self.bundles:
            b.selected = value
        self.show_list()

    def merge(self, arg: str) -> None:
        self._change(plan.merge(self.bundles, self._file_numbers(arg)))

    def split(self, arg: str) -> None:
        chapter = self._chapter(arg)
        self._change(plan.split(self.bundles, plan.find_bundle(self.bundles, chapter), chapter))

    def move(self, arg: str) -> None:
        parts = arg.split()
        if len(parts) != 2:
            raise ValueError("usage: v CH N, e.g. v 93 21")
        chapter = self._chapter(parts[0])
        (target,) = self._file_numbers(parts[1], exactly_one=True)
        self._change(plan.move(self.bundles, chapter, target))

    def undo(self, _arg: str) -> None:
        if not self.history:
            self.say("nothing to undo")
            return
        self.project.bundles = self.history.pop()
        self.show_list()

    def build(self, ask: Callable[[str], str]) -> int | None:
        manifest = Manifest(self.opts.out_dir)
        actions = plan_actions(self.bundles, self.opts, manifest)
        writes = [a for a in actions if a.writes]
        if not writes:
            self.say("nothing to write (all included files are up to date, existing or empty)")
            return None
        for a in writes:
            self.say(f"  {ACTION_TEXT[a.kind]:<18} {a.target.name}")
        if is_synced_folder(self.opts.out_dir):
            self.say(f"warning: {self.opts.out_dir} looks like a OneDrive folder; every file written will be uploaded")
        try:
            answer = ask(f"write {len(writes)} files to {self.opts.out_dir}? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in ("y", "yes"):
            self.say("not written")
            return None
        report = run_build(actions, self.opts, manifest, on_progress=self.say)
        for action, error in report.failed:
            self.say(f"failed {action.target.name}: {error}")
        self.say(f"done: {len(report.written)} files, {report.pages} pages written")
        return EXIT_BUILD_FAILED if report.failed else EXIT_OK

    def _change(self, new: list[Bundle]) -> None:
        self.history.append(self.bundles)
        self.project.bundles = new
        self.show_list()

    def _file_numbers(self, arg: str, exactly_one: bool = False) -> list[int]:
        if not arg:
            raise ValueError("give a file number from the list")
        numbers = sorted(plan.parse_int_ranges(arg.replace(" ", ",")))
        if exactly_one and len(numbers) != 1:
            raise ValueError("give exactly one file number")
        for n in numbers:
            if not 1 <= n <= len(self.bundles):
                raise ValueError(f"no file number {n}; the list has 1-{len(self.bundles)}")
        return [n - 1 for n in numbers]

    def _chapter(self, arg: str):
        try:
            number = Decimal(arg)
        except InvalidOperation:
            raise ValueError(f"{arg!r} is not a chapter number") from None
        chapter = plan.find_chapter(self.bundles, number)
        if chapter is None:
            raise ValueError(f"no chapter {arg} in the plan")
        return chapter
