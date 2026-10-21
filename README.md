# manga-cbz

Turns a folder of per-chapter manga downloads (HakuNeko, Mihon/Tachiyomi and similar) into one `.cbz` per volume, for e-readers like Kobo and servers like Komga or Kavita. Source folders are never modified.

```
Monster Musume no Iru Nichijou/              Monster Musume no Iru Nichijou (cbz)/
  Vol.01 Ch.0001 (en) [Group]/1.jpg ...        Monster Musume Vol.01.cbz
  Vol.06 Ch.0026.5 (en) [Group]/        ->      ...
  Ch.0093 (en) [Other Group]/                   Monster Musume Vol.20.cbz
```

Three ways to run it, all on the same core library:

| Mode | Use it for |
|---|---|
| `manga-cbz build` | One command with sensible defaults. Scriptable. |
| `manga-cbz interactive` | Reviewing and fixing the plan in a text menu before writing. Works over SSH. |
| `manga-cbz-gui.exe` | A desktop window on Windows. |

## Install

Windows: download `manga-cbz-gui.exe` (and `manga-cbz.exe` for the command line) from the Releases page. The exe is not code-signed, so SmartScreen will warn the first time.

From source (Python 3.10+, Windows or Linux):

```
pip install .            # command line only, no dependencies on 3.11+
pip install ".[gui]"     # adds the desktop window (PySide6)
```

## Command line

```
manga-cbz build "Monster Musume no Iru Nichijou" --series "Monster Musume" --dry-run
manga-cbz build "Monster Musume no Iru Nichijou" --series "Monster Musume"
```

Output goes to `<folder> (cbz)` next to the series folder unless `--out` is given. Run `manga-cbz build --help` for every flag. The common ones:

| Flag | Effect |
|---|---|
| `--dry-run` | Print exactly what would be written, write nothing. |
| `--series NAME` | Name used in output files. Characters invalid on Windows are removed. |
| `--per volume\|chapter\|all` | One file per volume (default), per chapter, or one file for everything. |
| `--trailing last\|new\|skip` | Where unlabelled chapters after the last volume go (see below). |
| `--assign 93-95=21` | Put chapters in a volume. Repeatable. Also `67.5=17`. |
| `--merge 1-3` | Merge volumes 1 to 3 into `Vol.01-03.cbz`. Repeatable. |
| `--split 48` | Start a new file at chapter 48 (`Vol.12 part 1`, `Vol.12 part 2`). |
| `--only 1-5,8` | Build only these volumes. |
| `--comicinfo` | Add `ComicInfo.xml` with series, volume, page count, language and scan groups. |
| `--overwrite` | Replace `.cbz` files this tool did not write. |
| `--strict` | Exit 4 without writing if there are any warnings. |
| `--pattern REGEX` | Custom chapter-name regex with a named group `ch` and optionally `vol`. |

Exit codes: 0 done, 1 a file failed to build, 2 bad arguments or input, 3 no chapters found, 4 warnings with `--strict`.

## Interactive mode

```
manga-cbz interactive "Monster Musume no Iru Nichijou"
```

Lists the planned files, then takes one-letter commands:

```
  1 [x] write      Monster Musume Vol.01.cbz  132p  Ch.1-4
 ...
 21 [x] write      Monster Musume Vol.21.cbz  111p  Ch.93-95*
> m 19-20        merge files 19 and 20
> v 93 20        move chapter 93 into file 20
> p 48           start a new file at chapter 48
> t 1-5          include/exclude files 1 to 5
> s 12           show the chapters in file 12, with page counts and warnings
> u              undo
> b              build (shows what will be written and asks first)
```

It accepts the same flags as `build`, so `--trailing`, `--assign` and the rest set the starting plan.

## Desktop window

`manga-cbz-gui.exe`, or `manga-cbz gui [folder]` from source. Pick the series folder, check the volumes to build, select files or chapters in the tree and use Merge, Split here or Move to. Build writes in the background; the log pane shows warnings and progress.

## How chapters are found

Each folder under the series folder whose name matches the pattern is a chapter. The default pattern accepts:

```
Vol.01 Ch.0001 (en) [Group]      Ch.0093 (en) [Group]      Vol.17 Ch.0067.5 - Title (en) [Group]
Volume 1 Chapter 3               v01 c003                  c003
```

- Chapter numbers are decimals, so 26 < 26.5 < 27.
- Pages are sorted naturally (1, 2, 10), across mixed `.jpg`/`.png`/`.webp`/`.gif`/`.avif`.
- Chapters that are already zipped (`Ch.0001.cbz` or `.zip`) are read directly.
- Images in subfolders of a chapter are included, in path order.
- A folder named like `Vol.03` or `Volume 3` that holds chapter folders gives its volume to the chapters inside.
- Non-image files are skipped and listed. Folders that don't match are listed as skipped.

## Chapters without a volume label

Chapters with no `Vol.` in the name are not dropped. Each one goes in the volume of the nearest labelled chapter below it by number. Every such placement is a guess: it prints a warning and is marked `*` in the plan.

Chapters after the last labelled one are usually not yet collected in a volume. `--trailing` decides where they go:

- `last` (default): append to the last volume.
- `new`: put them in a new volume, last + 1.
- `skip`: leave them out.

To correct guesses permanently, put a `volumes.toml` in the series folder. It is picked up automatically (or pass `--overrides FILE`). `--assign` on the command line beats the file.

```toml
93-95 = 21
67.5 = 17
```

## Warnings

- **Empty chapter**: no images.
- **Short chapter**: a whole-number chapter with fewer pages than 60% of the median (`--short` changes the fraction). Decimal chapters like 26.5 are extras and are not checked.
- **Gap**: whole chapter numbers missing from the sequence.
- **Duplicate**: the same chapter number twice, usually two groups' releases. Both are included; remove one or use `--pattern`.

## Output

- Files are named `<Series> Vol.NN.cbz`, with 3-digit volumes when there are more than 99.
- Each page is a top-level zip entry named `0001_Ch0001_1.jpg` (page index, chapter, original name), so alphabetical order is reading order. No inner folders.
- Pages are stored uncompressed by default. Images barely shrink and it is much faster. `--compress` turns on deflate.
- Each file is written as `*.cbz.tmp`, re-opened to check the entry count and CRCs, then renamed into place. A failed file leaves nothing behind and does not stop the others.

## Re-running

The output folder holds `.manga-cbz.json`, a record of what each file was built from (chapter names, page names and sizes, options). On a re-run, a file whose sources are unchanged is reported as up to date and not rewritten. When a new chapter arrives, only the affected volume is rebuilt.

Existing `.cbz` files that are not in that record are left alone unless `--overwrite` is given.

## OneDrive

Writing into a OneDrive folder starts an upload of every file (a full series can be several GB). The default output folder sits next to the series folder, so if the series is in OneDrive, pass `--out` somewhere else. The tool warns before writing into a path that looks like OneDrive. Cloud-only source files download as they are read, which is slow but works.

## Development

```
python -m venv .venv && .venv/bin/pip install -e ".[gui]" pytest
.venv/bin/pytest
```

Layout: `src/manga_cbz/` has the library (`naming`, `scan`, `plan`, `build`, `project`) and the three front ends (`cli`, `interactive`, `gui`). The library has no UI code. Tests build small synthetic series folders in a temp directory.

Pushing a tag like `v0.1.0` runs `.github/workflows/release.yml`, which tests on Windows, builds both exes with PyInstaller and attaches them to a GitHub release.

## Known limits

- Interactive mode is a line-based menu, not a full-screen terminal UI. It needs no extra packages and works in any terminal, including over SSH and on Windows.
- Merge, split and move edits in interactive mode and the GUI are not saved between sessions. Use `volumes.toml` or the command-line flags for a repeatable plan.
- Image types are checked by extension only.
