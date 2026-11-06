import bz2

from lexi_pipeline.wiktionary import (Sense, WikDictSource, WiktionaryDumpSource, english_fallback,
                                      parse_english_entry, pick_sense, strip_wikitext)
from lexi_pipeline.wordnet_source import WordNetSource
from lexi_pipeline.models import Entry
from tests.conftest import FIXTURES


def test_strip_wikitext():
    assert strip_wikitext("{{lb|en|countable}} A [[mammal]], ''[[Canis familiaris|dog]]''.") == "A mammal, dog."


def test_parse_english_section_only():
    text = (FIXTURES / "mini_wiktionary.xml").read_text()
    body = text.split('<text xml:space="preserve">')[1].split("</text>")[0]
    parsed = parse_english_entry(body)
    assert set(parsed) == {"noun", "verb"}
    noun = parsed["noun"][0]
    assert noun.gloss == "animal" and noun.ru_terms == ["собака", "пёс"]
    assert noun.definitions[0].startswith("A mammal, Canis familiaris, often kept as a pet")
    assert "chien" not in " ".join(noun.definitions)


def test_dump_source_streams_plain_and_bz2(tmp_path):
    xml = (FIXTURES / "mini_wiktionary.xml").read_bytes()
    packed = tmp_path / "dump.xml.bz2"
    packed.write_bytes(bz2.compress(xml))
    for path in (FIXTURES / "mini_wiktionary.xml", packed):
        src = WiktionaryDumpSource(path, wanted={"dog"})
        assert src.senses("dog", "noun")[0].ru_terms == ["собака", "пёс"]
        assert src.senses("chien", "noun") == []


def test_wikdict_source(mini_raw):
    src = WikDictSource(mini_raw / "wikdict-en-ru.sqlite3")
    senses = src.senses("dog", "noun")
    assert senses[0].ru_terms == ["пёс", "собака"]
    assert src.senses("dog", "verb") == []


def test_pick_sense_prefers_overlap_then_score():
    a = Sense("adult", ["взрослый"], 110)
    b = Sense("of a great size", ["большой"], 110)
    assert pick_sense([a, b], "above average in size").ru_terms == ["большой"]
    assert pick_sense([Sense("x", [], 200), a], None) is a
    assert pick_sense([], "anything") is None


def test_english_fallback_needs_three_words():
    assert english_fallback([Sense("animal", [], 1)]) is None
    assert english_fallback([Sense("very cold weather", [], 1)]) == "very cold weather"


def test_wordnet_enrich_and_groups():
    wn = WordNetSource()
    dog = Entry("dog-n", "dog", "noun", "A1", variants=["dog"])
    assert wn.enrich(dog)
    assert dog.group == "noun.animal" and dog.definitions[0].source == "wordnet"
    assert "dog" not in dog.definitions[0].text.lower().split()
    jeans = Entry("jeans-n", "jeans", "noun", "A1", variants=["jeans"])
    assert wn.enrich(jeans), "morphy normalisation should find 'jean'"
    big = Entry("big-adj", "big", "adjective", "A1", variants=["big"])
    small = Entry("small-adj", "small", "adjective", "A1", variants=["small"])
    wn.enrich(big), wn.enrich(small)
    assert big.group.startswith("adj:") and big.group != small.group
    quickly = Entry("quickly-adv", "quickly", "adverb", "A2", variants=["quickly"])
    wn.enrich(quickly)
    assert quickly.group.startswith("adj:")
