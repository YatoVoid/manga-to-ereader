from decimal import Decimal

import pytest

from tankobon.naming import (
    PatternError, ch_label, compile_pattern, natural_key, parse_name, safe_filename, volume_from_dir,
)

REGEX = compile_pattern()


@pytest.mark.parametrize("name, volume, chapter", [
    ("Vol.01 Ch.0001 (en) [Monster Musume]", 1, "1"),
    ("Vol.17 Ch.0067.5 - Cerea Prologue (en) [Monster Musume]", 17, "67.5"),
    ("Ch.0093 (en) [Futari wa Pretty Anon]", None, "93"),
    ("Volume 1 Chapter 3", 1, "3"),
    ("v01 c003", 1, "3"),
    ("c003", None, "3"),
    ("Chapter 12.5", None, "12.5"),
])
def test_parse_name(name, volume, chapter):
    parsed = parse_name(name, REGEX)
    assert parsed.volume == volume
    assert parsed.chapter == Decimal(chapter)


def test_parse_name_metadata():
    parsed = parse_name("Vol.17 Ch.0067.5 - Cerea Prologue (en) [Monster Musume]", REGEX)
    assert (parsed.title, parsed.language, parsed.group) == ("Cerea Prologue", "en", "Monster Musume")


@pytest.mark.parametrize("name", ["Cerea", "Extras", "Vol.01", "cover"])
def test_parse_name_rejects(name):
    assert parse_name(name, REGEX) is None


def test_custom_pattern_needs_ch_group():
    with pytest.raises(PatternError):
        compile_pattern(r"Episode (\d+)")
    regex = compile_pattern(r"Episode (?P<ch>\d+)")
    assert parse_name("My Show Episode 4", regex).chapter == 4


def test_bad_regex_is_pattern_error():
    with pytest.raises(PatternError):
        compile_pattern("(")


def test_volume_from_dir():
    assert volume_from_dir("Vol.03") == 3
    assert volume_from_dir("Volume 12 - Title") == 12
    assert volume_from_dir("Various") is None


def test_natural_sort():
    assert sorted(["10.jpg", "2.png", "1.jpg"], key=natural_key) == ["1.jpg", "2.png", "10.jpg"]


def test_decimal_chapters_sort_numerically():
    assert sorted([Decimal("27"), Decimal("26.5"), Decimal("26")]) == [26, Decimal("26.5"), 27]


def test_ch_label():
    assert ch_label(Decimal("1")) == "0001"
    assert ch_label(Decimal("0067.5")) == "0067.5"


def test_safe_filename():
    assert safe_filename('Re:Zero <Part> "1"?') == "ReZero Part 1"
    assert safe_filename("Name. ") == "Name"
    assert safe_filename("CON") == "_CON"
    assert safe_filename("???") == ""
