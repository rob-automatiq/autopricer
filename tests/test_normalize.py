import pytest

from autopricer.normalize import row_key, row_ordinal, section_key


@pytest.mark.parametrize("raw,want", [
    ("Lower Level 112", "112"),
    ("Upper Level 228", "228"),
    ("lower level 101", "101"),
    ("Club Level 7", "7"),
    ("112", "112"),
    ("  112  ", "112"),
    # Floor sections are zero-padded on the listings side, bare on the sales
    # side; both must land on the same key or the two never join.
    ("06", "6"),
    ("6", "6"),
    ("03", "3"),
    ("010", "10"),
])
def test_section_key_canonicalises(raw, want):
    assert section_key(raw) == want


@pytest.mark.parametrize("raw", [
    None, "", "   ", "7th St.", "Parking Lot B", "Lower Level", "GA",
])
def test_section_key_rejects_non_sections(raw):
    assert section_key(raw) is None


def test_listing_and_sale_labels_agree():
    assert section_key("Lower Level 06") == section_key("06") == section_key("6")


@pytest.mark.parametrize("raw,want", [
    ("A", 1), ("a", 1), ("Z", 26), ("M", 13),
    # Target Center genuinely uses I and O as rows, so the alphabet is not
    # skipped the way some venues do.
    ("I", 9), ("O", 15),
    ("1", 1), ("5", 5), ("12", 12),
])
def test_row_ordinal(raw, want):
    assert row_ordinal(raw) == want


def test_row_ordinal_i_and_o_are_distinct_from_neighbours():
    assert row_ordinal("H") == 8
    assert row_ordinal("I") == 9
    assert row_ordinal("J") == 10
    assert row_ordinal("N") == 14
    assert row_ordinal("O") == 15
    assert row_ordinal("P") == 16


@pytest.mark.parametrize("raw", [
    None, "", "TBD", "tbd", "PACKAGE", "ZZ", "PARKI..", "0", "99",
])
def test_row_ordinal_is_none_for_placeholders(raw):
    assert row_ordinal(raw) is None


def test_row_key_upper_cases_but_keeps_placeholders():
    assert row_key(" c ") == "C"
    assert row_key("tbd") == "TBD"
    assert row_key(None) is None
