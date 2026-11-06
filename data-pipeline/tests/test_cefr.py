from lexi_pipeline.cefr import build_entries, lookup_variants, make_id, read_cefr_csv
from tests.conftest import FIXTURES


def test_lookup_variants_cover_spelling_and_hyphenation():
    assert lookup_variants("colour/color")[:2] == ["colour", "color"]
    assert "filmmaker" in lookup_variants("film-maker")
    assert "ice cream" in lookup_variants("ice cream")


def test_ids_are_unique_per_pos():
    assert make_id("Ice cream", "noun") == "ice_cream-n"
    assert make_id("fast", "adjective") != make_id("fast", "adverb")


def test_build_entries_dedupes_keeps_lowest_level_and_skips_function_words():
    entries, skipped = build_entries(read_cefr_csv(FIXTURES / "mini_cefrj.csv"))
    dogs = [e for e in entries if e.lemma == "dog"]
    assert len(dogs) == 1 and dogs[0].level == "A1"
    assert {s["headword"] for s in skipped} == {"the", "in"}
    assert all(s["reason"] == "unsupported_pos" for s in skipped)
    assert len({e.id for e in entries}) == len(entries)
    colour = next(e for e in entries if e.lemma == "colour")
    assert colour.variants[:2] == ["colour", "color"]
