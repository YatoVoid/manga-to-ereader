"""Desktop window (PySide6)."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import plan
from .build import BuildOptions, Manifest, plan_actions, run_build
from .model import Bundle, Chapter
from .project import InputError, Project, Settings, default_out_dir, is_synced_folder, load_project, series_name

STATUS_TEXT = {
    "write": "new",
    "rebuild": "changed",
    "overwrite": "overwrite",
    "up-to-date": "up to date",
    "exists": "exists, skipped",
    "empty": "no pages",
}
TRAILING_LABELS = {"last": "add to last volume", "new": "new volume", "skip": "leave out"}
FLAG_KINDS = ("guessed", "short", "empty", "duplicate")
COL_FILE, COL_STATUS, COL_PAGES, COL_CHAPTERS, COL_NOTES = range(5)


class BuildWorker(QObject):
    progress = Signal(str)
    finished = Signal(object)

    def __init__(self, actions, opts, manifest):
        super().__init__()
        self.actions, self.opts, self.manifest = actions, opts, manifest

    def run(self):
        try:
            report = run_build(self.actions, self.opts, self.manifest, on_progress=self.progress.emit)
        except Exception as e:  # report anything unexpected in the log instead of losing it in the thread
            report = e
        self.finished.emit(report)


class MainWindow(QMainWindow):
    def __init__(self, folder: Path | None = None):
        super().__init__()
        self.setWindowTitle("Tankobon")
        self.resize(1000, 700)
        self.project: Project | None = None
        self.history: list[list[Bundle]] = []
        self.flags: dict[int, list[str]] = {}
        self.thread: QThread | None = None
        self._auto_out = ""

        self.folder_edit = QLineEdit()
        self.out_edit = QLineEdit()
        self.series_edit = QLineEdit()
        self.per_combo = QComboBox()
        self.per_combo.addItems(plan.PER_CHOICES)
        self.trailing_combo = QComboBox()
        for key, label in TRAILING_LABELS.items():
            self.trailing_combo.addItem(label, key)
        self.comicinfo_check = QCheckBox("Add ComicInfo.xml")
        self.compress_check = QCheckBox("Compress")
        self.overwrite_check = QCheckBox("Overwrite existing files")

        browse_in = QPushButton("Browse...")
        browse_in.clicked.connect(self.choose_folder)
        browse_out = QPushButton("Browse...")
        browse_out.clicked.connect(self.choose_out)
        scan_btn = QPushButton("Scan")
        scan_btn.clicked.connect(self.scan)
        self.per_combo.currentIndexChanged.connect(self.rescan_if_loaded)
        self.trailing_combo.currentIndexChanged.connect(self.rescan_if_loaded)
        for check in (self.comicinfo_check, self.overwrite_check):
            check.toggled.connect(self.refresh)
        self.series_edit.editingFinished.connect(self.refresh)
        self.out_edit.editingFinished.connect(self.refresh)

        form = QGridLayout()
        form.addWidget(QLabel("Series folder:"), 0, 0)
        form.addWidget(self.folder_edit, 0, 1, 1, 3)
        form.addWidget(browse_in, 0, 4)
        form.addWidget(scan_btn, 0, 5)
        form.addWidget(QLabel("Output folder:"), 1, 0)
        form.addWidget(self.out_edit, 1, 1, 1, 3)
        form.addWidget(browse_out, 1, 4)
        form.addWidget(QLabel("Series name:"), 2, 0)
        form.addWidget(self.series_edit, 2, 1)
        form.addWidget(QLabel("One file per:"), 2, 2)
        form.addWidget(self.per_combo, 2, 3)
        form.addWidget(QLabel("Unlabelled chapters after the last volume:"), 3, 0, 1, 2)
        form.addWidget(self.trailing_combo, 3, 2, 1, 2)
        options = QHBoxLayout()
        for check in (self.comicinfo_check, self.compress_check, self.overwrite_check):
            options.addWidget(check)
        options.addStretch()
        form.addLayout(options, 4, 0, 1, 6)
        form.setColumnStretch(1, 1)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["File / chapter", "Status", "Pages", "Chapters", "Notes"])
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.header().setSectionResizeMode(COL_FILE, QHeaderView.Stretch)
        for col in (COL_STATUS, COL_PAGES, COL_CHAPTERS, COL_NOTES):
            self.tree.header().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.tree.itemChanged.connect(self.on_item_changed)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.tree)
        splitter.addWidget(self.log)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        self.merge_btn = QPushButton("Merge")
        self.merge_btn.setToolTip("Merge the selected files into one")
        self.merge_btn.clicked.connect(self.merge)
        self.split_btn = QPushButton("Split here")
        self.split_btn.setToolTip("Start a new file at the selected chapter")
        self.split_btn.clicked.connect(self.split)
        self.move_btn = QPushButton("Move to...")
        self.move_btn.setToolTip("Move the selected chapters into another file")
        self.move_btn.clicked.connect(self.move)
        self.undo_btn = QPushButton("Undo")
        self.undo_btn.clicked.connect(self.undo)
        self.undo_btn.setEnabled(False)
        all_btn = QPushButton("Check all")
        all_btn.clicked.connect(lambda: self.set_all(True))
        none_btn = QPushButton("Check none")
        none_btn.clicked.connect(lambda: self.set_all(False))
        self.build_btn = QPushButton("Build")
        self.build_btn.setDefault(True)
        self.build_btn.clicked.connect(self.build)
        buttons = QHBoxLayout()
        for b in (self.merge_btn, self.split_btn, self.move_btn, self.undo_btn, all_btn, none_btn):
            buttons.addWidget(b)
        buttons.addStretch()
        buttons.addWidget(self.build_btn)
        self.edit_buttons = (self.merge_btn, self.split_btn, self.move_btn, self.undo_btn, all_btn, none_btn,
                             self.build_btn, scan_btn)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(splitter, 1)
        layout.addLayout(buttons)
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        self.progress = QProgressBar()
        self.progress.setMaximumWidth(200)
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)

        if folder is not None:
            self.folder_edit.setText(str(folder))
            self.scan()

    def say(self, text: str) -> None:
        self.log.appendPlainText(text)

    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Series folder", self.folder_edit.text())
        if folder:
            self.folder_edit.setText(folder)
            self.scan()

    def choose_out(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Output folder", self.out_edit.text())
        if folder:
            self.out_edit.setText(folder)
            self.refresh()

    def rescan_if_loaded(self) -> None:
        if self.project is not None:
            self.scan()

    def scan(self) -> None:
        text = self.folder_edit.text().strip()
        if not text:
            return
        root = Path(text)
        if not self.out_edit.text().strip() or self.out_edit.text() == self._auto_out:
            self._auto_out = str(default_out_dir(root))
            self.out_edit.setText(self._auto_out)
        if not self.series_edit.text().strip():
            self.series_edit.setText(root.name)
        settings = Settings(per=self.per_combo.currentText(), trailing=self.trailing_combo.currentData())
        try:
            project = load_project(root, settings, exclude=(Path(self.out_edit.text()),))
        except (InputError, OSError) as e:
            self.say(f"error: {e}")
            return
        self.project = project
        self.history.clear()
        self.flags = {}
        for issue in project.issues:
            if issue.chapter is not None and issue.kind in FLAG_KINDS:
                self.flags.setdefault(id(issue.chapter), []).append(issue.kind)
        self.say(f"scanned {root}: {len(project.chapters)} chapters, {len(project.bundles)} files")
        if project.overrides_used:
            self.say(f"using overrides from {project.overrides_used}")
        for name in project.skipped:
            self.say(f"warning: skipped folder (no chapter number): {name}")
        for issue in project.issues:
            self.say(f"warning: {issue.message}")
        self.refresh()

    def options(self) -> BuildOptions | None:
        try:
            series = series_name(Path(self.folder_edit.text()), self.series_edit.text() or None)
        except InputError as e:
            self.say(f"error: {e}")
            return None
        out = self.out_edit.text().strip()
        if not out:
            self.say("error: choose an output folder")
            return None
        return BuildOptions(Path(out), series, self.comicinfo_check.isChecked(),
                            self.compress_check.isChecked(), self.overwrite_check.isChecked())

    def refresh(self) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        opts = self.options() if self.project else None
        if self.project is None or opts is None:
            self.tree.blockSignals(False)
            return
        actions = {id(a.bundle): a for a in plan_actions(self.project.bundles, opts, Manifest(opts.out_dir))}
        for b in self.project.bundles:
            action = actions.get(id(b))
            notes = sorted({k for c in b.chapters for k in self.flags.get(id(c), [])})
            item = QTreeWidgetItem([
                b.filename(opts.series),
                STATUS_TEXT[action.kind] if action else "",
                str(b.page_count),
                plan.chapter_span(b.chapters),
                ", ".join(notes),
            ])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(COL_FILE, Qt.Checked if b.selected else Qt.Unchecked)
            item.setTextAlignment(COL_PAGES, Qt.AlignRight | Qt.AlignVCenter)
            for c in b.chapters:
                vol = "" if c.volume is None else f"vol {c.volume}" + (" (guessed)" if c.guessed else "")
                child = QTreeWidgetItem([c.name, vol, str(len(c.pages)), str(c.number),
                                         ", ".join(self.flags.get(id(c), []))])
                child.setTextAlignment(COL_PAGES, Qt.AlignRight | Qt.AlignVCenter)
                item.addChild(child)
            self.tree.addTopLevelItem(item)
        self.tree.blockSignals(False)
        self.undo_btn.setEnabled(bool(self.history))

    def on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != COL_FILE or item.parent() is not None or self.project is None:
            return
        index = self.tree.indexOfTopLevelItem(item)
        self.project.bundles[index].selected = item.checkState(COL_FILE) == Qt.Checked

    def selected_bundles(self) -> list[int]:
        rows = set()
        for item in self.tree.selectedItems():
            top = item.parent() or item
            rows.add(self.tree.indexOfTopLevelItem(top))
        return sorted(rows)

    def selected_chapters(self) -> list[Chapter]:
        chapters = []
        for item in self.tree.selectedItems():
            parent = item.parent()
            if parent is not None:
                bundle = self.project.bundles[self.tree.indexOfTopLevelItem(parent)]
                chapters.append(bundle.chapters[parent.indexOfChild(item)])
        return chapters

    def change(self, new: list[Bundle]) -> None:
        self.history.append(self.project.bundles)
        self.project.bundles = new
        self.refresh()

    def merge(self) -> None:
        if self.project is None:
            return
        try:
            self.change(plan.merge(self.project.bundles, self.selected_bundles()))
        except plan.PlanError as e:
            self.say(f"merge: {e}")

    def split(self) -> None:
        chapters = self.selected_chapters() if self.project else []
        if len(chapters) != 1:
            self.say("split: select one chapter; it becomes the first chapter of the new file")
            return
        bundles = self.project.bundles
        try:
            self.change(plan.split(bundles, plan.find_bundle(bundles, chapters[0]), chapters[0]))
        except plan.PlanError as e:
            self.say(f"split: {e}")

    def move(self) -> None:
        chapters = self.selected_chapters() if self.project else []
        if not chapters:
            self.say("move: select one or more chapters first")
            return
        opts = self.options()
        if opts is None:
            return
        names = [b.filename(opts.series) for b in self.project.bundles]
        name, ok = QInputDialog.getItem(self, "Move chapters", f"Move {len(chapters)} chapter(s) to:", names, 0, False)
        if not ok:
            return
        target_bundle = self.project.bundles[names.index(name)]
        bundles = self.project.bundles
        try:
            for c in chapters:
                target = next(i for i, b in enumerate(bundles) if b.label == target_bundle.label)
                bundles = plan.move(bundles, c, target)
        except plan.PlanError as e:
            self.say(f"move: {e}")
            return
        self.change(bundles)

    def undo(self) -> None:
        if self.history:
            self.project.bundles = self.history.pop()
            self.refresh()

    def set_all(self, value: bool) -> None:
        if self.project is None:
            return
        for b in self.project.bundles:
            b.selected = value
        self.refresh()

    def build(self) -> None:
        if self.project is None:
            self.say("scan a series folder first")
            return
        opts = self.options()
        if opts is None:
            return
        manifest = Manifest(opts.out_dir)
        actions = plan_actions(self.project.bundles, opts, manifest)
        writes = [a for a in actions if a.writes]
        if not writes:
            self.say("nothing to write: checked files are up to date, already exist, or have no pages")
            return
        text = f"Write {len(writes)} file(s) to {opts.out_dir}?"
        if is_synced_folder(opts.out_dir):
            text += "\n\nThis looks like a OneDrive folder. Every file written will be uploaded."
        if QMessageBox.question(self, "Build", text) != QMessageBox.Yes:
            return
        for b in self.edit_buttons:
            b.setEnabled(False)
        self.progress.setRange(0, len(writes))
        self.progress.setValue(0)
        self.progress.show()

        self.thread = QThread(self)
        self.worker = BuildWorker(actions, opts, manifest)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.finished.connect(self.thread.quit)
        self.thread.start()

    def on_progress(self, text: str) -> None:
        self.say(text)
        self.progress.setValue(self.progress.value() + 1)

    def on_finished(self, report) -> None:
        self.progress.hide()
        for b in self.edit_buttons:
            b.setEnabled(True)
        if isinstance(report, Exception):
            self.say(f"build stopped: {report}")
        else:
            for action, pages in report.written:
                self.say(f"wrote {action.target.name}: {pages} pages, {action.target.stat().st_size / 1e6:.1f} MB")
            for action, error in report.failed:
                self.say(f"failed {action.target.name}: {error}")
            self.say(f"done: {len(report.written)} files, {report.pages} pages")
        self.refresh()

    def closeEvent(self, event) -> None:
        if self.thread is not None and self.thread.isRunning():
            QMessageBox.information(self, "Build running", "Wait for the build to finish before closing.")
            event.ignore()
            return
        super().closeEvent(event)


def main(folder: Path | None = None) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow(folder)
    window.show()
    return app.exec()


def entry() -> int:
    """Entry point for the tankobon-gui script and the .exe: an optional folder argument."""
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    return main(Path(args[0]) if args else None)


if __name__ == "__main__":
    sys.exit(entry())
