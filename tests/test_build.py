import zipfile
from xml.etree import ElementTree as ET

import pytest

from conftest import make_archive_chapter, make_chapter, snapshot

from manga_cbz.build import MANIFEST_NAME, BuildOptions, Manifest, plan_actions, run_build, write_cbz
from manga_cbz.project import Settings, load_project


def build_all(root, out, **kw):
    project = load_project(root, Settings(), exclude=(out,))
    opts = BuildOptions(out, "Test", **kw)
    manifest = Manifest(out)
    actions = plan_actions(project.bundles, opts, manifest)
    return actions, run_build(actions, opts, manifest)


def test_cbz_pages_are_flat_and_in_reading_order(series, tmp_path):
    out = tmp_path / "out"
    _, report = build_all(series, out)
    assert not report.failed
    with zipfile.ZipFile(out / "Test Vol.01.cbz") as z:
        names = z.namelist()
    assert names == sorted(names)
    assert all("/" not in n for n in names)
    assert names[0] == "0001_Ch0001_1.jpg"
    assert names[9] == "0010_Ch0001_10.jpg"
    assert names[20] == "0021_Ch0002.5_1.jpg"
    assert len(names) == 10 + 10 + 2 + 10


def test_source_is_never_modified(series, tmp_path):
    before = snapshot(series)
    build_all(series, tmp_path / "out", comicinfo=True)
    assert snapshot(series) == before


def test_comicinfo(series, tmp_path):
    out = tmp_path / "out"
    build_all(series, out, comicinfo=True)
    with zipfile.ZipFile(out / "Test Vol.02.cbz") as z:
        assert z.namelist()[0] == "ComicInfo.xml"
        info = ET.fromstring(z.read("ComicInfo.xml"))
    assert info.findtext("Series") == "Test"
    assert info.findtext("Volume") == "2"
    assert info.findtext("PageCount") == str(10 + 3 + 10 + 10)
    assert info.findtext("ScanInformation") == "Group B"
    assert info.findtext("LanguageISO") == "en"


def test_existing_file_not_ours_is_skipped_unless_overwrite(series, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "Test Vol.01.cbz").write_bytes(b"someone else's file")
    actions, report = build_all(series, out)
    assert {a.target.name: a.kind for a in actions}["Test Vol.01.cbz"] == "exists"
    assert (out / "Test Vol.01.cbz").read_bytes() == b"someone else's file"

    actions, report = build_all(series, out, overwrite=True)
    assert {a.target.name: a.kind for a in actions}["Test Vol.01.cbz"] == "overwrite"
    assert zipfile.is_zipfile(out / "Test Vol.01.cbz")


def test_rerun_rebuilds_only_the_changed_volume(series, tmp_path):
    out = tmp_path / "out"
    build_all(series, out)
    assert (out / MANIFEST_NAME).is_file()
    actions, _ = build_all(series, out)
    assert {a.kind for a in actions} == {"up-to-date"}

    make_chapter(series, "Ch.0008 (en) [Group B]", 10)
    actions, report = build_all(series, out)
    kinds = {a.target.name: a.kind for a in actions}
    assert kinds == {"Test Vol.01.cbz": "up-to-date", "Test Vol.02.cbz": "rebuild"}
    assert len(report.written) == 1


def test_archive_chapters_are_copied(tmp_path):
    root = tmp_path / "s"
    make_archive_chapter(root, "Vol.01 Ch.0001.cbz", 3)
    make_chapter(root, "Vol.01 Ch.0002", 2)
    out = tmp_path / "out"
    _, report = build_all(root, out)
    assert report.pages == 5
    with zipfile.ZipFile(out / "Test Vol.01.cbz") as z:
        assert z.namelist()[:3] == ["0001_Ch0001_1.jpg", "0002_Ch0001_2.jpg", "0003_Ch0001_3.jpg"]
        assert z.testzip() is None


def test_failed_write_leaves_no_partial_file(series, tmp_path):
    project = load_project(series, Settings())
    bundle = project.bundles[0]
    bundle.chapters[0].pages[0].source.unlink()
    target = tmp_path / "x.cbz"
    with pytest.raises(OSError):
        write_cbz(bundle, target, BuildOptions(tmp_path, "Test"))
    assert list(tmp_path.glob("x.cbz*")) == []


def test_one_failure_does_not_stop_the_rest(series, tmp_path):
    project = load_project(series, Settings())
    project.bundles[0].chapters[0].pages[0].source.unlink()
    opts = BuildOptions(tmp_path / "out", "Test")
    manifest = Manifest(opts.out_dir)
    report = run_build(plan_actions(project.bundles, opts, manifest), opts, manifest)
    assert [a.target.name for a, _ in report.failed] == ["Test Vol.01.cbz"]
    assert [a.target.name for a, _ in report.written] == ["Test Vol.02.cbz"]
