from manga_cbz.build import BuildOptions
from manga_cbz.cli import EXIT_OK
from manga_cbz.interactive import run
from manga_cbz.project import Settings, load_project


def session(series, tmp_path, *lines):
    project = load_project(series, Settings(trailing="new"))
    opts = BuildOptions(tmp_path / "out", "T")
    answers = iter(lines)
    output = []
    code = run(project, opts, ask=lambda _prompt: next(answers), say=output.append)
    return code, "\n".join(output), project


def test_merge_move_undo_and_build(series, tmp_path):
    code, output, project = session(series, tmp_path, "m 1-2", "v 7 1", "u", "t 2", "b", "y")
    assert code == EXIT_OK
    assert [b.label for b in project.bundles] == ["Vol.01-02", "Vol.03"]
    assert sorted(p.name for p in (tmp_path / "out").glob("*.cbz")) == ["T Vol.01-02.cbz"]


def test_build_needs_confirmation(series, tmp_path):
    code, output, _ = session(series, tmp_path, "b", "n", "q")
    assert code == EXIT_OK
    assert "not written" in output
    assert not (tmp_path / "out").exists()


def test_bad_commands_do_not_crash(series, tmp_path):
    code, output, _ = session(series, tmp_path, "zz", "s 99", "p 1", "v 1", "m 1", "u", "q")
    assert code == EXIT_OK
    assert output.count("error:") == 4
    assert "unknown command" in output
    assert "nothing to undo" in output


def test_show_lists_chapters(series, tmp_path):
    _, output, _ = session(series, tmp_path, "s 1", "q")
    assert "Ch.3" in output and "vol 1*" in output


def test_eof_quits(series, tmp_path):
    project = load_project(series, Settings())

    def ask(_prompt):
        raise EOFError

    assert run(project, BuildOptions(tmp_path / "out", "T"), ask=ask, say=lambda _s: None) == EXIT_OK
