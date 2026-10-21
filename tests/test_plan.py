from decimal import Decimal

import pytest

from tankobon import plan
from tankobon.naming import compile_pattern
from tankobon.project import InputError, Settings, load_project
from tankobon.scan import scan


def chapters_of(root):
    return scan(root, compile_pattern()).chapters


def volumes(chapters):
    return {str(c.number): c.volume for c in chapters}


def test_unlabelled_middle_chapter_goes_with_previous_volume(series):
    chapters, issues = plan.assign_unlabelled(chapters_of(series), "last")
    v = volumes(chapters)
    assert v["3"] == 1
    assert next(c for c in chapters if c.number == 3).guessed
    assert {i.kind for i in issues} == {"guessed"}


@pytest.mark.parametrize("trailing, expected", [("last", 2), ("new", 3)])
def test_trailing_chapters(series, trailing, expected):
    chapters, _ = plan.assign_unlabelled(chapters_of(series), trailing)
    assert volumes(chapters)["6"] == expected
    assert volumes(chapters)["7"] == expected


def test_trailing_skip_leaves_them_out(series):
    chapters, issues = plan.assign_unlabelled(chapters_of(series), "skip")
    assert "6" not in volumes(chapters) and "7" not in volumes(chapters)
    assert "3" in volumes(chapters)
    assert [i.kind for i in issues].count("skipped") == 2


def test_unlabelled_before_first_volume(tmp_path):
    from conftest import make_chapter
    make_chapter(tmp_path / "s", "Ch.0001")
    make_chapter(tmp_path / "s", "Vol.02 Ch.0002")
    chapters, _ = plan.assign_unlabelled(chapters_of(tmp_path / "s"))
    assert volumes(chapters)["1"] == 2


def test_checks_flag_short_and_empty_but_not_extras(series):
    from conftest import make_chapter
    make_chapter(series, "Vol.02 Ch.0004.5", 0)
    chapters, _ = plan.assign_unlabelled(chapters_of(series))
    issues = plan.check_chapters(chapters)
    by_kind = {(i.kind, str(i.chapter.number)) for i in issues if i.chapter}
    assert ("short", "5") in by_kind
    assert ("empty", "4.5") in by_kind
    assert not any(k == "short" and n == "2.5" for k, n in by_kind)


def test_checks_flag_gaps_and_duplicates(tmp_path):
    from conftest import make_chapter
    for name in ["Ch.0001 [A]", "Ch.0001 [B]", "Ch.0004"]:
        make_chapter(tmp_path / "s", name)
    issues = plan.check_chapters(chapters_of(tmp_path / "s"))
    messages = [i.message for i in issues]
    assert any("2-3 missing" in m for m in messages)
    assert any(i.kind == "duplicate" for i in issues)


def test_overrides_file(series):
    (series / "volumes.toml").write_text("6-7 = 3\n2.5 = 2\n")
    project = load_project(series, Settings())
    v = volumes(project.chapters)
    assert (v["6"], v["7"], v["2.5"]) == (3, 3, 2)
    assert not any(c.guessed for c in project.chapters if c.number in (6, 7))
    assert [b.label for b in project.bundles] == ["Vol.01", "Vol.02", "Vol.03"]


def test_assign_beats_overrides_file(series):
    (series / "volumes.toml").write_text('"6-7" = 3\n')
    project = load_project(series, Settings(assign=[plan.parse_assign("7=4")]))
    assert volumes(project.chapters)["7"] == 4


@pytest.mark.parametrize("text", ["6-7 = 'three'", "7-6 = 3", "abc = 3", "6 = ["])
def test_bad_overrides_are_input_errors(series, text):
    (series / "volumes.toml").write_text(text)
    with pytest.raises(InputError):
        load_project(series, Settings())


def test_group_by_volume_chapter_all(series):
    chapters, _ = plan.assign_unlabelled(chapters_of(series))
    assert [b.label for b in plan.group(chapters, "volume")] == ["Vol.01", "Vol.02"]
    assert [b.label for b in plan.group(chapters, "chapter")][:3] == ["Ch.0001", "Ch.0002", "Ch.0002.5"]
    assert [b.label for b in plan.group(chapters, "all")] == [""]


def test_three_digit_volumes(tmp_path):
    from conftest import make_chapter
    make_chapter(tmp_path / "s", "Vol.100 Ch.0001")
    make_chapter(tmp_path / "s", "Vol.99 Ch.0000")
    labels = [b.label for b in plan.group(chapters_of(tmp_path / "s"))]
    assert labels == ["Vol.099", "Vol.100"]


def test_merge_split_move(series):
    chapters, _ = plan.assign_unlabelled(chapters_of(series), "new")
    bundles = plan.group(chapters)
    merged = plan.merge(bundles, [0, 1])
    assert [b.label for b in merged] == ["Vol.01-02", "Vol.03"]
    assert len(bundles) == 3, "merge must not change the original list"

    ch5 = plan.find_chapter(merged, Decimal(5))
    parts = plan.split(merged, 0, ch5)
    assert [b.label for b in parts] == ["Vol.01-02 part 1", "Vol.01-02 part 2", "Vol.03"]
    assert parts[1].chapters[0] is ch5

    ch7 = plan.find_chapter(parts, Decimal(7))
    moved = plan.move(parts, ch7, 0)
    assert ch7 in moved[0].chapters
    assert moved[0].chapters[-1] is ch7


def test_move_last_chapter_drops_empty_file(series):
    chapters, _ = plan.assign_unlabelled(chapters_of(series), "new")
    bundles = plan.group(chapters)
    for number in (6, 7):
        bundles = plan.move(bundles, plan.find_chapter(bundles, Decimal(number)), 1)
    assert [b.label for b in bundles] == ["Vol.01", "Vol.02"]


def test_split_at_first_chapter_is_an_error(series):
    bundles = plan.group(plan.assign_unlabelled(chapters_of(series))[0])
    with pytest.raises(plan.PlanError):
        plan.split(bundles, 0, bundles[0].chapters[0])


def test_chapter_span(series):
    chapters, _ = plan.assign_unlabelled(chapters_of(series))
    vol1 = plan.group(chapters)[0].chapters
    assert plan.chapter_span(vol1) == "1-2, 2.5, 3*"


def test_parse_int_ranges():
    assert plan.parse_int_ranges("1-3,5") == {1, 2, 3, 5}
    with pytest.raises(plan.PlanError):
        plan.parse_int_ranges("x")
