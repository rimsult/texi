"""Technical deck: field classification, filters and level estimation."""
from types import SimpleNamespace

import pytest

from lexi_pipeline.technical import (FIELDS, MIN_ESTIMATED_LEVEL, TechClassifier, acceptable_lemma, calibrate,
                                     estimate_level, label_field, parse_seeds, pick_tech_sense, resolve_seed)
from lexi_pipeline.text import clean_gloss, leaks
from lexi_pipeline.wordnet_source import WordNetSource
from tests.conftest import make_entry


@pytest.fixture(scope="module")
def clf():
    return TechClassifier(WordNetSource().wn)


@pytest.mark.parametrize("gloss,field", [
    ("computing: input device", "it"),
    ("(mathematics) set of equations to be solved simultaneously", "math"),
    ("chemistry: substance made by chemical combination of elements", "chemistry"),
    ("electronics: electrode of a vacuum tube", "electrical"),
    ("cooking: a dish", None),
    ("animal", None),
    (None, None),
])
def test_label_field(gloss, field):
    assert label_field(gloss) == field


@pytest.mark.parametrize("synset,field", [
    ("transistor.n.01", "electrical"),
    ("algorithm.n.01", "it"),
    ("hydrogen.n.01", "chemistry"),
    ("triangle.n.01", "math"),
    ("engine.n.01", "engineering"),
    ("electron.n.01", "physics"),
])
def test_classifier_maps_synsets_to_fields(clf, synset, field):
    s = clf.wn.synset(synset)
    assert (clf.by_topic(s) or clf.by_root(s)) == field


@pytest.mark.parametrize("synset", ["dog.n.01", "apple.n.01", "clock.n.01", "hour.n.01", "dollar.n.01"])
def test_classifier_ignores_everyday_concepts(clf, synset):
    s = clf.wn.synset(synset)
    assert clf.by_topic(s) is None and clf.by_root(s) is None


def test_acceptable_lemma_filters():
    z = {"voltage": 3.9, "cool": 5.0, "ohm": 1.8, "network": 4.8}.get
    zipf = lambda w: z(w, 0.0)  # noqa: E731
    assert acceptable_lemma("voltage", zipf)
    assert not acceptable_lemma("cool", zipf)  # stoplist: everyday sense dominates
    assert not acceptable_lemma("ohm", zipf)  # too rare to be useful
    assert not acceptable_lemma("hard disk", zipf)  # single plain words only
    assert acceptable_lemma("network", zipf, "noun") and not acceptable_lemma("network", zipf, "verb")


def test_level_estimation_is_calibrated_and_floored():
    entries = [make_entry(f"w{i}", w, level=lv) for i, (w, lv) in enumerate(
        [("a", "A1"), ("b", "A2"), ("c", "B1"), ("d", "B2"), ("e", "C1"), ("f", "C2")])]
    z = dict(a=6.0, b=5.0, c=4.0, d=3.0, e=2.0, f=1.0)
    thresholds = calibrate(entries, lambda w: z[w])
    assert thresholds == [5.5, 4.5, 3.5, 2.5, 1.5]
    assert estimate_level(6.5, thresholds) == MIN_ESTIMATED_LEVEL == "B1"  # never "elementary"
    assert estimate_level(3.0, thresholds) == "B2"
    assert estimate_level(0.5, thresholds) == "C2"


def test_russian_sense_needs_evidence():
    sense = lambda gloss, *ru: SimpleNamespace(gloss=gloss, ru_terms=list(ru))  # noqa: E731
    silver = [sense("items made of silver or other white metal", "серебряные изделия"),
              sense("metal", "серебро"), sense("coins", "серебро")]
    gloss = "a soft white precious univalent metallic element"
    assert pick_tech_sense(silver, gloss, "chemistry", "silver").ru_terms == ["серебро"]
    computer = [sense("person", "вычислитель"), sense("programmable electronic device", "компьютер")]
    assert pick_tech_sense(computer, "a machine for performing calculations automatically", "it",
                           "computer").ru_terms == ["компьютер"]
    sink = [sense(None, "раковина"), sense("wastewater drain", "слив")]
    assert pick_tech_sense(sink, "a process that acts to absorb or remove energy", "physics", "sink") is None


def test_seed_terms_resolve_to_a_usable_sense(clf):
    """Every hand-picked core term maps to a WordNet sense of that very word, with a
    learner-friendly gloss that does not contain the word itself."""
    seeds = parse_seeds()
    assert len(seeds) > 350
    assert {f for _, _, f, _ in seeds} == set(FIELDS)
    for lemma, pos, fid, pinned in seeds:
        sense = resolve_seed(clf.wn, clf, lemma, pos, fid, pinned)
        assert sense is not None, lemma
        assert lemma in {l.name().lower() for l in sense.lemmas()}, lemma
        gloss = clean_gloss(sense.definition())
        assert gloss and not leaks(gloss, [lemma]), (lemma, gloss)


@pytest.mark.parametrize("lemma,pos,field,expected", [
    ("velocity", "noun", "physics", "speed.n.01"),  # WordNet files it under "rate", not physics
    ("piston", "noun", "engineering", "piston.n.02"),  # not Walter Piston, the composer
    ("nucleus", "noun", "physics", "nucleus.n.02"),  # the atom's, not the cell's
    ("encryption", "noun", "it", "encoding.n.01"),
])
def test_seed_senses(clf, lemma, pos, field, expected):
    pinned = next(p for l, ps, f, p in parse_seeds() if l == lemma and ps == pos)
    assert resolve_seed(clf.wn, clf, lemma, pos, field, pinned).name() == expected
