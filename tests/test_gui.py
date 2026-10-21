import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication

from tankobon.gui import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_window_scans_merges_and_undoes(app, series, tmp_path):
    window = MainWindow(series)
    window.out_edit.setText(str(tmp_path / "out"))
    window.refresh()
    tree = window.tree
    assert tree.topLevelItemCount() == 2
    assert not window.undo_btn.isEnabled()

    tree.topLevelItem(0).setSelected(True)
    tree.topLevelItem(1).setSelected(True)
    window.merge()
    assert [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())] == ["Test Series Vol.01-02.cbz"]
    window.undo()
    assert tree.topLevelItemCount() == 2
    window.close()
