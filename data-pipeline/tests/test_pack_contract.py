"""Contract tests over the real, shipped content packs."""
import hashlib
import re
import json

import pytest

from lexi_pipeline.models import LEVELS, MAX_GENERATED_QUALITY, level_index
from lexi_pipeline.text import leaks, ru_mentions
from tests.conftest import PACKS

pytestmark = pytest.mark.skipif(not (PACKS / "manifest.json").exists(), reason="packs not built")


DECKS = ("general", "tech")


@pytest.fixture(scope="module")
def manifest():
    return json.loads((PACKS / "manifest.json").read_text())


@pytest.fixture(scope="module")
def decks(manifest):
    """deck -> level -> pack"""
    return {d["id"]: {l["level"]: json.loads((PACKS / l["file"]).read_text()) for l in d["levels"]}
            for d in manifest["decks"]}


@pytest.fixture(scope="module")
def packs(decks):
    return decks["general"]


@pytest.fixture(scope="module")
def lexicons(decks):
    return {deck: {e["id"]: e for p in packs.values() for e in p["entries"]} for deck, packs in decks.items()}


@pytest.fixture(scope="module")
def lexicon(lexicons):
    return {k: v for lex in lexicons.values() for k, v in lex.items()}


def best_def(entry, lang):
    defs = [d for d in entry["definitions"] if d["lang"] == lang]
    return max(defs, key=lambda d: d["quality"])["text"] if defs else None


def test_manifest_matches_files(manifest, decks):
    assert manifest["schemaVersion"] == 2
    assert [d["id"] for d in manifest["decks"]] == list(DECKS)
    for deck in manifest["decks"]:
        assert deck["title"] and deck["description"]
        assert [l["level"] for l in deck["levels"]] == list(LEVELS)
        for item in deck["levels"]:
            body = (PACKS / item["file"]).read_bytes()
            assert hashlib.sha256(body).hexdigest()[:12] == item["hash"]
            pack = decks[deck["id"]][item["level"]]
            assert pack["deck"] == deck["id"] and pack["level"] == item["level"]
            assert item["words"] == len({q["entryId"] for q in pack["questions"]})
            hard = {}
            for q in pack["questions"]:
                if q.get("hard"):
                    key = f"{q['trainer']}:{q['lang']}"
                    hard[key] = hard.get(key, 0) + 1
            assert item["hard"] == hard
    assert all(s["license"] for s in manifest["sources"])
    assert set(manifest["fields"]) == {"it", "electrical", "physics", "math", "chemistry", "engineering"}


def test_every_word_ships_once_per_deck(decks):
    for deck, packs in decks.items():
        ids = [e["id"] for p in packs.values() for e in p["entries"]]
        assert len(ids) == len(set(ids)), deck
        for lv, p in packs.items():
            assert all(e["level"] == lv for e in p["entries"])


def test_tech_deck_entries(manifest, decks, lexicons):
    tech = lexicons["tech"]
    assert len(tech) > 1000
    assert all(i.startswith("tech:") and e["domain"] in manifest["fields"] for i, e in tech.items())
    assert not any(i.startswith("tech:") for i in lexicons["general"])
    fields = {e["domain"] for e in tech.values()}
    assert fields == set(manifest["fields"])
    lemmas = {e["lemma"] for e in tech.values()}
    # core terms of every field (hand-picked seeds) are present
    assert {"algorithm", "compiler", "bandwidth", "voltage", "transistor", "impedance", "velocity", "torque",
            "entropy", "photon", "vector", "logarithm", "eigenvalue", "molecule", "catalyst", "polymer",
            "piston", "crankshaft", "alloy"} <= lemmas
    # every level has something to train, words outside CEFR lists start at B1
    for lv, p in decks["tech"].items():
        assert p["questions"], lv


def test_language_policy(decks):
    for deck, packs in decks.items():
        for lv in ("B1", "B2", "C1", "C2"):
            assert all(q["lang"] == "en" for q in packs[lv]["questions"]), (deck, lv)
        for lv in ("B2", "C1", "C2"):  # B1 words may carry Russian: they serve as A2 distractors
            assert all(d["lang"] == "en" for e in packs[lv]["entries"] for d in e["definitions"]), (deck, lv)
        for lv in ("A1", "A2"):
            assert {q["lang"] for q in packs[lv]["questions"]} == {"en", "ru"}, (deck, lv)


def test_distractor_rules_hold_for_every_shipped_question(decks, lexicons):
    checked = 0
    for deck, packs in decks.items():
        lexicon = lexicons[deck]
        for lv, p in packs.items():
            for q in p["questions"]:
                t = lexicon[q["entryId"]]
                assert t["level"] == lv and t["group"]
                assert len(q["distractors"]) >= 2
                tdef = best_def(t, q["lang"])
                seen = {tdef.lower()}
                for did in q["distractors"]:
                    d = lexicon[did]
                    assert d["pos"] == t["pos"]
                    assert abs(level_index(d["level"]) - level_index(t["level"])) <= 1
                    assert d["group"] and d["group"] != t["group"]
                    assert d["lemma"].lower() != t["lemma"].lower()
                    if q["trainer"] == "word-to-definition":
                        best = best_def(d, q["lang"])
                        assert best, (q, did)
                        assert best.lower() not in seen, (q, did)
                        seen.add(best.lower())
                    checked += 1
    assert checked > 50_000


def test_hard_mode_rules_hold_for_every_hard_pool(decks, lexicons):
    """Hard options: same narrow semantic group, but never a near-synonym, never the same
    adjective cluster, never a duplicate or leaking definition — one correct answer."""
    checked = 0
    for deck, packs in decks.items():
        lexicon = lexicons[deck]
        for lv, p in packs.items():
            for q in p["questions"]:
                if "hard" not in q:
                    continue
                t = lexicon[q["entryId"]]
                assert len(q["hard"]) >= 2
                group = t.get("hardGroup", t["group"])
                tdef = best_def(t, q["lang"])
                seen = {tdef.lower()}
                lemmas = {t["lemma"].lower()}
                for hid in q["hard"]:
                    h = lexicon[hid]
                    assert h["pos"] == t["pos"]
                    assert abs(level_index(h["level"]) - level_index(t["level"])) <= 1
                    assert h.get("hardGroup", h["group"]) == group, (t["id"], hid)
                    if t["group"].startswith("adj:"):
                        assert h["group"] != t["group"], (t["id"], hid)
                    assert h["lemma"].lower() not in lemmas
                    lemmas.add(h["lemma"].lower())
                    hdef = best_def(h, q["lang"])
                    assert hdef and hdef.lower() not in seen, (t["id"], hid)
                    seen.add(hdef.lower())
                    assert not leaks(hdef, [t["lemma"]]), (t["id"], hid)
                    assert not leaks(tdef, [h["lemma"]]), (t["id"], hid)
                    checked += 1
    assert checked > 50_000


def test_hard_mode_coverage(manifest):
    for deck in manifest["decks"]:
        total = sum(sum(l["questions"].values()) for l in deck["levels"])
        hard = sum(sum(l["hard"].values()) for l in deck["levels"])
        assert hard / total > 0.6, deck["id"]


def test_definitions_are_labelled_and_do_not_give_answer_away(lexicon):
    for e in lexicon.values():
        assert e["definitions"], e["id"]
        for d in e["definitions"]:
            assert d["lang"] in ("en", "ru")
            assert d["source"] in ("wordnet", "wiktionary", "simple", "generated", "machine")
            if d["lang"] == "ru":
                assert d["source"] == "machine", (e["id"], d)  # always a translated definition
            if d["source"] == "generated":
                assert d["quality"] <= MAX_GENERATED_QUALITY
            else:
                assert d["quality"] > MAX_GENERATED_QUALITY
            if d["lang"] == "en":
                assert not leaks(d["text"], [e["lemma"]]), (e["lemma"], d["text"])


def test_dictionary_definition_preferred_over_generated(lexicon):
    for e in lexicon.values():
        by_lang = {}
        for d in e["definitions"]:
            by_lang.setdefault(d["lang"], []).append(d)
        for defs in by_lang.values():
            best = max(defs, key=lambda d: d["quality"])
            if any(d["source"] != "generated" for d in defs):
                assert best["source"] != "generated"


def test_general_deck_is_extended_beyond_the_cefr_lists(lexicons, packs):
    general = lexicons["general"]
    assert len(general) > 11_000
    for lv in ("B2", "C1", "C2"):
        assert len(packs[lv]["entries"]) > 1000, lv
    lemmas = {e["lemma"] for e in general.values()}
    assert {"attorney", "ratio", "density", "footage"} <= lemmas  # frequent words missing from CEFR lists
    assert not {"john", "harry", "bullshit", "made", "longer"} & lemmas  # names, slang, inflections


def test_russian_mode_uses_translated_definitions(decks):
    """Russian options are full translated definitions, not one-word translations, and the
    short translation ships only where Russian questions exist (A1–A2)."""
    for deck, packs in decks.items():
        texts = [d["text"] for lv in ("A1", "A2") for e in packs[lv]["entries"] for d in e["definitions"]
                 if d["lang"] == "ru"]
        assert texts, deck
        assert sum(len(t.split()) >= 3 for t in texts) / len(texts) > 0.8, deck
        assert not [t for t in texts if re.search(r"[A-Za-z]{2,}|^[A-Za-z]\b", t)], deck
        with_translation = [e for lv in ("A1", "A2") for e in packs[lv]["entries"] if e.get("translation")]
        assert len(with_translation) > 0.5 * sum(len(packs[lv]["entries"]) for lv in ("A1", "A2")), deck
        for lv in ("B1", "B2", "C1", "C2"):
            assert not any("translation" in e for e in packs[lv]["entries"]), (deck, lv)


def test_russian_options_do_not_name_the_answer(decks, lexicons):
    """«молодая собака» (puppy) is never an option for "dog" in Russian mode, and the
    definition shown in definition → word never contains a distractor's translation."""
    checked = 0
    for deck, packs in decks.items():
        lexicon = lexicons[deck]
        for lv in ("A1", "A2"):
            for q in packs[lv]["questions"]:
                if q["lang"] != "ru":
                    continue
                t = lexicon[q["entryId"]]
                tterms = t.get("translation", "").split(", ") if t.get("translation") else []
                tdef = best_def(t, "ru")
                for did in {*q["distractors"], *q.get("hard", [])}:
                    d = lexicon[did]
                    dterms = d.get("translation", "").split(", ") if d.get("translation") else []
                    assert not ru_mentions(best_def(d, "ru"), tterms), (t["id"], did)
                    assert not ru_mentions(tdef, dterms), (t["id"], did)
                    checked += 1
    assert checked > 10_000


def test_one_definition_per_language_ships(lexicon):
    for e in lexicon.values():
        langs = [d["lang"] for d in e["definitions"]]
        assert len(langs) == len(set(langs)), e["id"]


def test_low_levels_get_learner_definitions(packs):
    """A1–B1 words are explained in basic English (Simple English Wiktionary) where it exists;
    C1–C2 keep the precise dictionary gloss."""
    def share(lv):
        defs = [d for e in packs[lv]["entries"] for d in e["definitions"] if d["lang"] == "en"]
        return sum(d["source"] == "simple" for d in defs) / len(defs)
    assert share("A1") > 0.6 and share("A2") > 0.6 and share("B1") > 0.5
    assert share("C1") < 0.2 and share("C2") < 0.2



def test_no_definition_has_a_blank(lexicon):
    """Learner frames ("If you ___ something, …") are rewritten into dictionary form or
    replaced by the WordNet gloss: no shipped definition contains "___"."""
    assert not [e["id"] for e in lexicon.values() for d in e["definitions"] if "___" in d["text"]]


def test_gap_fill_questions(manifest, decks, lexicons):
    """Optional gap-fill trainer: the span points at the answer's form inside its example,
    options are distinct words of the same part of speech from other semantic groups,
    and no option already occurs in the sentence."""
    total = 0
    for deck, packs in decks.items():
        lexicon = lexicons[deck]
        levels = {lv["level"]: lv for d in manifest["decks"] if d["id"] == deck for lv in d["levels"]}
        for lv, p in packs.items():
            gaps = [q for q in p["questions"] if q["trainer"] == "gap-fill"]
            assert levels[lv]["questions"].get("gap-fill:en", 0) == len(gaps)
            for q in gaps:
                t = lexicon[q["entryId"]]
                s, e = q["span"]
                assert q["lang"] == "en" and 0 <= s < e <= len(t["example"])
                assert t["example"][s:e] == q["forms"][0], t["id"]
                assert len(q["forms"]) == len(q["distractors"]) + 1 >= 3
                assert len({f.lower() for f in q["forms"]}) == len(q["forms"]), t["id"]
                sentence = t["example"].lower()
                for did, form in zip(q["distractors"], q["forms"][1:]):
                    d = lexicon[did]
                    assert d["pos"] == t["pos"] and d["group"] != t["group"], (t["id"], did)
                    if t.get("hardGroup", "").startswith("adjfam:"):
                        assert d.get("hardGroup") != t["hardGroup"], (t["id"], did)
                    assert not re.search(rf"(?<![\w-]){re.escape(form.lower())}(?![\w-])", sentence), (t["id"], form)
                total += 1
    assert total > 3000


def test_examples_are_translated_only_where_russian_is_used(decks):
    for deck, packs in decks.items():
        low = [e for lv in ("A1", "A2") for e in packs[lv]["entries"] if e.get("example")]
        with_ru = [e for e in low if e.get("exampleRu")]
        assert len(with_ru) > 0.5 * len(low), deck
        assert all(re.search("[а-яё]", e["exampleRu"], re.I) and not re.search(r"[A-Za-z]{3,}", e["exampleRu"])
                   for e in with_ru), deck
        for lv in ("B1", "B2", "C1", "C2"):
            assert not any("exampleRu" in e for e in packs[lv]["entries"]), (deck, lv)


def test_synonyms_are_short_lists_of_other_words(lexicon):
    with_syn = [e for e in lexicon.values() if e.get("synonyms")]
    assert len(with_syn) > 1000
    for e in with_syn:
        assert 1 <= len(e["synonyms"]) <= 3 and e["lemma"] not in e["synonyms"], e["id"]


def test_tech_levels_count_questions_per_field(manifest):
    tech = next(d for d in manifest["decks"] if d["id"] == "tech")
    for lv in tech["levels"]:
        fields = lv["fields"]
        assert set(fields) <= set(manifest["fields"])
        for key, n in lv["questions"].items():
            assert sum(f["questions"].get(key, 0) for f in fields.values()) == n, (lv["level"], key)
