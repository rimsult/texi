"""General-deck expansion: frequent WordNet words beyond the CEFR lists."""
import pytest

from lexi_pipeline.extra import BLOCKLIST, LEVEL_FLOOR, collect_extra, extra_entries
from lexi_pipeline.models import level_index
from lexi_pipeline.wordnet_source import WordNetSource

ZIPF = {"attorney": 4.69, "ratio": 4.37, "density": 4.33, "heyday": 3.09, "john": 4.9, "made": 5.9,
        "longer": 4.6, "glasses": 4.4, "bullshit": 4.47, "dog": 5.5, "zxqv": 4.0, "chandelier": 3.19,
        "thermistor": 2.0, "obscureword": 1.0}


@pytest.fixture(scope="module")
def wn():
    return WordNetSource().wn


@pytest.fixture(scope="module")
def cands(wn):
    known = {"dog", "make", "long", "glass"}
    return collect_extra(wn, lambda w: ZIPF.get(w, 0.0), known, exclude={"density"})


def test_frequent_unlisted_words_are_added_most_frequent_first(cands):
    lemmas = [c.lemma for c in cands]
    assert lemmas[:3] == ["attorney", "ratio", "chandelier"]
    assert "heyday" in lemmas and all(c.count >= 1 for c in cands)


def test_names_forms_slang_and_known_words_are_skipped(cands):
    lemmas = {c.lemma for c in cands}
    assert not lemmas & {"john", "made", "longer", "glasses", "bullshit", "dog", "density", "thermistor"}
    assert "bullshit" in BLOCKLIST


def test_extra_entries_get_estimated_levels_from_b2(cands):
    thresholds = [4.75, 4.37, 3.98, 3.53, 3.08]
    entries = extra_entries(cands, thresholds, taken={"ratio-n"})
    by = {e.lemma: e for e in entries}
    assert "ratio" not in by  # id already taken
    assert by["attorney"].level == LEVEL_FLOOR  # frequent, but an unlisted word is never elementary
    assert by["heyday"].level == "C1" and by["chandelier"].level == "C1"
    assert all(level_index(e.level) >= level_index("B2") and e.level_source == "frequency" for e in entries)
