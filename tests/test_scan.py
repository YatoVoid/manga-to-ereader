from decimal import Decimal

from conftest import JPEG, make_archive_chapter, make_chapter

from manga_cbz.naming import compile_pattern
from manga_cbz.scan import scan

REGEX = compile_pattern()


def test_scan_finds_and_sorts_chapters(series):
    result = scan(series, REGEX)
    assert [str(c.number) for c in result.chapters] == ["1", "2", "2.5", "3", "4", "5", "6", "7"]
    assert result.chapters[3].volume is None
    assert result.chapters[0].group == "Group A"


def test_pages_sort_naturally_with_mixed_extensions(tmp_path):
    folder = tmp_path / "s" / "Ch.0001"
    folder.mkdir(parents=True)
    for name in ["10.png", "2.jpg", "1.jpg", "3.PNG"]:
        (folder / name).write_bytes(JPEG)
    (chapter,) = scan(tmp_path / "s", REGEX).chapters
    assert [p.name for p in chapter.pages] == ["1.jpg", "2.jpg", "3.PNG", "10.png"]


def test_non_image_files_are_skipped_and_reported(tmp_path):
    folder = make_chapter(tmp_path / "s", "Ch.0001", 2)
    (folder / "notes.txt").write_text("x")
    (folder / "Thumbs.db").write_bytes(b"x")
    result = scan(tmp_path / "s", REGEX)
    assert len(result.chapters[0].pages) == 2
    assert [i.kind for i in result.issues] == ["non-image"]
    assert "notes.txt" in result.issues[0].message


def test_unmatched_folders_are_listed(tmp_path):
    make_chapter(tmp_path / "s", "Ch.0001")
    (tmp_path / "s" / "Extras").mkdir()
    result = scan(tmp_path / "s", REGEX)
    assert result.skipped == ["Extras"]


def test_archive_chapters(tmp_path):
    make_archive_chapter(tmp_path / "s", "Vol.02 Ch.0010.cbz", 4)
    make_archive_chapter(tmp_path / "s", "Ch.0011.zip", 2)
    chapters = scan(tmp_path / "s", REGEX).chapters
    assert [(c.number, c.volume, len(c.pages)) for c in chapters] == [(10, 2, 4), (11, None, 2)]
    assert chapters[0].pages[0].in_archive


def test_broken_archive_is_reported(tmp_path):
    (tmp_path / "s").mkdir()
    (tmp_path / "s" / "Ch.0001.cbz").write_bytes(b"not a zip")
    result = scan(tmp_path / "s", REGEX)
    assert result.chapters == []
    assert result.issues[0].kind == "unreadable"


def test_volume_folders_give_their_volume(tmp_path):
    make_chapter(tmp_path / "s" / "Volume 3", "Chapter 12")
    make_chapter(tmp_path / "s" / "Volume 3", "Chapter 13")
    chapters = scan(tmp_path / "s", REGEX).chapters
    assert [(c.number, c.volume) for c in chapters] == [(12, 3), (13, 3)]


def test_nested_images_inside_a_chapter(tmp_path):
    folder = make_chapter(tmp_path / "s", "Ch.0001", 1)
    (folder / "part2").mkdir()
    (folder / "part2" / "1.jpg").write_bytes(JPEG)
    (chapter,) = scan(tmp_path / "s", REGEX).chapters
    assert [p.rel for p in chapter.pages] == ["1.jpg", "part2/1.jpg"]


def test_excluded_output_folder_is_not_scanned(tmp_path):
    make_chapter(tmp_path / "s", "Ch.0001")
    make_chapter(tmp_path / "s" / "out", "Ch.0002")
    result = scan(tmp_path / "s", REGEX, exclude=(tmp_path / "s" / "out",))
    assert [c.number for c in result.chapters] == [Decimal(1)]
