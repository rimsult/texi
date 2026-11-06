from lexi_pipeline.text import (
    clean_gloss,
    clean_ru_terms,
    leaks,
    load_frequency,
    rank_ru_terms,
    ru_mentions,
    stem,
    strip_stress,
)


def test_strip_stress_keeps_yo():
    assert strip_stress("соба́ка") == "собака"
    assert strip_stress("всё") == "всё"


def test_clean_gloss_drops_parentheticals_and_extra_clauses():
    g = "a member of the genus Canis (probably descended from the common wolf); occurs in many breeds"
    assert clean_gloss(g) == "a member of the genus Canis"


def test_clean_gloss_cuts_long_text_at_phrase_boundary():
    long = ("a system of world-wide electronic communication in which a computer user can compose a message "
            "at one terminal that can be regenerated at the recipient's terminal when the recipient logs in")
    out = clean_gloss(long)
    assert out is not None and len(out.split()) <= 22 and out.startswith("a system of world-wide")


def test_clean_gloss_rejects_empty():
    assert clean_gloss("(rare)") is None


def test_leaks_detects_headword_inflections_and_stems():
    assert leaks("the dog barked", ["dog"])
    assert leaks("several dogs", ["dog"])
    assert leaks("in a philanthropic manner", ["philanthropically"])
    assert leaks("a person who teaches", ["teacher"])
    assert leaks("a card used for credit purchases", ["credit card"])
    assert not leaks("a daily or weekly publication on folded sheets", ["newspaper"])
    assert not leaks("a domesticated carnivorous mammal", ["dog"])


def test_stem_keeps_short_words():
    assert stem("quickly") == "quick"
    assert stem("bus") == "bus"


def test_clean_ru_terms_dedupes_and_filters_markup():
    assert clean_ru_terms("пёс | соба́ка | собака | [[та́блица]] | dog") == ["пёс", "собака"]
    assert len(clean_ru_terms("а | б | в | г | д", limit=3)) == 3


def test_rank_ru_terms_prefers_common_single_words(tmp_path):
    freq_file = tmp_path / "ru.txt"
    freq_file.write_text("и 100\nприйти 50\nприехать 40\nприбыть 10\nдостигать 5\n", encoding="utf-8")
    freq = load_frequency(freq_file)
    terms = ["прибывать", "достигать", "прийти", "приехать", "прибыть на место"]
    assert rank_ru_terms(terms, freq) == ["прийти", "приехать", "достигать"]
    # Without a frequency list the source order is kept.
    assert rank_ru_terms(terms, None, limit=2) == ["прибывать", "достигать"]


def test_clean_gloss_drops_examples_after_a_colon():
    g = "feline mammal usually having thick soft fur and no ability to roar: domestic cats; wildcats"
    assert clean_gloss(g) == "feline mammal usually having thick soft fur and no ability to roar"
    assert clean_gloss("ratio: of two numbers") == "ratio: of two numbers"  # short heads are kept


def test_ru_mentions_finds_inflected_translations():
    assert ru_mentions("молодая собака", {"собака"})
    assert ru_mentions("хозяин собаки", ["собака", "пёс"])
    assert not ru_mentions("маленькое домашнее животное", {"собака"})
    assert not ru_mentions("кот на крыше", {"кот"})  # too short to compare safely
    assert not ru_mentions("большой дом", {"жилой дом"})  # multi-word translations are skipped


def test_sensitive_words_by_part_of_speech():
    from lexi_pipeline.text import sensitive
    assert sensitive("Goddamn", "adjective") and sensitive("gay", "adjective")
    assert sensitive("screw", "verb") and not sensitive("screw", "noun")  # a screw is just a screw
    assert sensitive("bloody", "adjective") and not sensitive("dog", "noun")
