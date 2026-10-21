import zipfile

from conftest import make_chapter

from manga_cbz.cli import EXIT_NO_CHAPTERS, EXIT_OK, EXIT_USAGE, EXIT_WARNINGS, main


def test_dry_run_writes_nothing(series, tmp_path, capsys):
    out = tmp_path / "out"
    assert main(["build", str(series), "--out", str(out), "--dry-run"]) == EXIT_OK
    assert not out.exists()
    stdout = capsys.readouterr().out
    assert "Test Series Vol.01.cbz" in stdout
    assert "3*" in stdout


def test_build_default_out_is_next_to_series(series, capsys):
    assert main(["build", str(series), "--series", "Test"]) == EXIT_OK
    out = series.parent / "Test Series (cbz)"
    assert sorted(p.name for p in out.glob("*.cbz")) == ["Test Vol.01.cbz", "Test Vol.02.cbz"]


def test_flags_merge_only_assign(series, tmp_path, capsys):
    out = tmp_path / "out"
    code = main(["build", str(series), "--out", str(out), "--series", "T",
                 "--assign", "6-7=3", "--merge", "1-2", "--only", "1-2"])
    assert code == EXIT_OK
    assert [p.name for p in out.glob("*.cbz")] == ["T Vol.01-02.cbz"]


def test_split_flag(series, tmp_path):
    out = tmp_path / "out"
    assert main(["build", str(series), "--out", str(out), "--series", "T", "--split", "2.5"]) == EXIT_OK
    with zipfile.ZipFile(out / "T Vol.01 part 2.cbz") as z:
        assert z.namelist()[0] == "0001_Ch0002.5_1.jpg"


def test_strict_exits_on_warnings(series, tmp_path):
    out = tmp_path / "out"
    assert main(["build", str(series), "--out", str(out), "--strict"]) == EXIT_WARNINGS
    assert not out.exists()


def test_no_chapters(tmp_path):
    (tmp_path / "empty").mkdir()
    assert main(["build", str(tmp_path / "empty"), "--dry-run"]) == EXIT_NO_CHAPTERS


def test_usage_errors(series, tmp_path, capsys):
    assert main(["build", str(tmp_path / "missing")]) == EXIT_USAGE
    assert main(["build", str(series), "--assign", "6-7"]) == EXIT_USAGE
    assert main(["build", str(series), "--merge", "1"]) == EXIT_USAGE
    assert main(["build", str(series), "--split", "1"]) == EXIT_USAGE
    assert main(["build", str(series), "--pattern", "nope"]) == EXIT_USAGE
    assert main(["build", str(series), "--series", "???"]) == EXIT_USAGE
    assert "error:" in capsys.readouterr().err


def test_custom_pattern(tmp_path):
    make_chapter(tmp_path / "s", "Episode 1")
    make_chapter(tmp_path / "s", "Episode 2")
    out = tmp_path / "out"
    code = main(["build", str(tmp_path / "s"), "--out", str(out), "--per", "all", "--series", "Show",
                 "--pattern", r"Episode (?P<ch>\d+)"])
    assert code == EXIT_OK
    assert (out / "Show.cbz").is_file()
