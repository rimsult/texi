"""Level-adaptive definitions: the learner definition where it is easier, the precise one above."""
from collections import Counter

import pytest

from conftest import make_entry
from lexi_pipeline.adapt import Vocabulary, adapt_definitions, cost, prefers_simple, readability_report
from lexi_pipeline.simple_wiktionary import SimpleEntry, SimpleSense, SimpleWiktionary
from lexi_pipeline.wordnet_source import WordNetSource

BASIC = ("a short visit to place during journey vehicle with two wheels you use your legs make it move bus "
         "little clock person arm near hand measure time").split()


@pytest.fixture(scope="module")
def wn():
    return WordNetSource()


@pytest.fixture
def vocab(wn):
    # Basic words are A1; everything else is "rare" (frequency 0 → C2).
    return Vocabulary({w: 0 for w in BASIC}, lambda w: 0.0, [6, 5, 4, 3, 2], wn.wn)


SIMPLE = SimpleWiktionary({
    ("stop", "noun"): SimpleEntry("stop", "noun", [
        SimpleSense(0, "A stop is a short visit to a place during a journey.", ["We made a stop in Paris."])]),
    ("bicycle", "noun"): SimpleEntry("bicycle", "noun", [
        SimpleSense(0, "A bicycle is a vehicle with two wheels. You use your legs to make it move.",
                    ["She rides her bicycle to school."])]),
    ("address", "noun"): SimpleEntry("address", "noun", [SimpleSense(0, "Your address is the place where you live.")]),
    ("watch", "noun"): SimpleEntry("watch", "noun", [
        SimpleSense(0, "A watch is a little clock on a person's arm near the person's hand, to measure time."),
        SimpleSense(1, "A watch is the period of time on duty for crews who are working together.")]),
})


def entry(wn, id, lemma, level, deck="general"):
    e = make_entry(id, lemma, level=level, deck=deck, level_source="cefr")
    e.definitions = []
    wn.enrich(e)
    return e


def test_cost_counts_levels_above_the_learner(vocab):
    assert cost(vocab, "a vehicle with two wheels", 1) == 0
    assert cost(vocab, "a vehicle moved by foot pedals", 1) == 2 * 4  # foot, pedals: C2 at A2+1; moved → move
    assert cost(vocab, "a vehicle with two wheels", 5) == 0
    assert vocab.difficulty("a vehicle with pedals", 1) == 0.5


def test_prefers_simple_depends_on_level():
    assert prefers_simple("A1", 3, 1) and not prefers_simple("A1", 4, 1)  # small price for basic words
    assert prefers_simple("B2", 1, 2) and not prefers_simple("B2", 2, 2)  # whichever is easier
    assert not prefers_simple("C1", 2, 4) and prefers_simple("C2", 1, 4)  # only when far easier
    assert prefers_simple("C1", 5, None)  # nothing to compare with


def test_low_levels_get_the_learner_definition(wn, vocab):
    bike = entry(wn, "bicycle-n", "bicycle", "A1")
    stats, log = Counter(), []
    adapt_definitions([bike], SIMPLE, wn, vocab, stats, log)
    best = bike.best_definition("en")
    assert (best.source, best.text) == ("simple", "a vehicle with two wheels; you use your legs to make it move")
    assert any(d.source == "wordnet" for d in bike.definitions)  # kept for editors / fallbacks
    assert bike.example == "She rides her bicycle to school."
    assert bike.mt_source == best.text  # nothing masked → same text is translated
    assert stats["simple_used:A1"] == 1 and log[0]["reason"] == "used"
    assert readability_report([bike], vocab) == {"A1": 0.0}


def test_high_levels_keep_the_precise_gloss(wn, vocab):
    bike = entry(wn, "bicycle-n", "bicycle", "C1")
    stats = Counter()
    adapt_definitions([bike], SIMPLE, wn, vocab, stats)
    assert bike.best_definition("en").source == "wordnet"
    assert stats["simple_not_easier"] == 1


def test_general_entry_follows_the_sense_of_its_learner_definition(wn, vocab):
    stop = entry(wn, "stop-n", "stop", "A1")
    assert stop.synset == "stop.n.01"  # "the event of something ending"
    adapt_definitions([stop], SIMPLE, wn, vocab, Counter())
    assert stop.synset == "stop.n.03" and stop.sense_changed
    texts = {d.source: d.text for d in stop.definitions}
    assert texts == {"wordnet": "a brief stay in the course of a journey",
                     "simple": "a short visit to a place during a journey"}
    assert stop.example == "We made a stop in Paris."


def test_technical_sense_is_not_replaced_by_the_everyday_one(wn, vocab):
    address = entry(wn, "tech:address-n", "address", "B2", deck="tech")
    stats = Counter()
    adapt_definitions([address], SIMPLE, wn, vocab, stats)
    assert address.best_definition("en").source == "wordnet"
    assert stats["simple_sense_unmatched"] == 1


def test_leaking_or_missing_entries_are_skipped(wn, vocab):
    cat = entry(wn, "cat-n", "cat", "A1")
    leaky = SimpleWiktionary({("cat", "noun"): SimpleEntry("cat", "noun", [SimpleSense(0, "Plural of cats.")])})
    stats = Counter()
    adapt_definitions([cat], leaky, wn, vocab, stats)
    adapt_definitions([cat], SimpleWiktionary(), wn, vocab, stats)
    assert stats["simple_unusable"] == 1 and stats["simple_found"] == 1
    assert cat.best_definition("en").source == "wordnet"


def test_general_words_get_their_main_learner_sense(wn, vocab):
    """The second Simple sense matches WordNet far better (period, time, duty, crew), but an A1
    learner meets "watch" as the clock on your arm."""
    watch = entry(wn, "watch-n", "watch", "A1")
    adapt_definitions([watch], SIMPLE, wn, vocab, Counter())
    assert watch.synset == "watch.n.01" and not watch.sense_changed
    assert watch.best_definition("en").text == "a little clock on a person's arm near the person's hand, to measure time"
