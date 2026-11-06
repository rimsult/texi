from lexi_pipeline.models import MAX_GENERATED_QUALITY, QUALITY
from lexi_pipeline.templates import generate_en, generate_ru, ru_adverb

GLOSSES = {
    ("quick", "adjective"): "accomplished rapidly and without delay",
    ("happy", "adjective"): "enjoying or showing or marked by joy or pleasure",
    ("blurt", "verb"): "utter impulsively",
    ("luxury", "noun"): "something that is an indulgence rather than a necessity",
}


def lookup(word, pos):
    g = GLOSSES.get((word, pos))
    return (g, f"{word}.syn") if g else None


def test_generated_definitions_are_marked_and_rank_below_dictionaries():
    gen = generate_en("quickly", "adverb", lookup)
    assert gen.definition.text == "in a way that is accomplished rapidly and without delay"
    assert gen.definition.source == "generated"
    assert gen.definition.quality <= MAX_GENERATED_QUALITY < min(QUALITY["wordnet"], QUALITY["wiktionary_gloss"])
    assert gen.base_word == "quick" and gen.rule == "adverb_from_adjective"


def test_negation_and_quality_noun_templates():
    assert generate_en("unhappy", "adjective", lookup).definition.text.startswith("not enjoying")
    assert generate_en("happiness", "noun", lookup).definition.text.startswith("the quality or state of being")


def test_conversion_only_for_true_lexical_gaps():
    assert generate_en("blurt", "noun", lookup).rule == "noun_from_verb"
    assert generate_en("blurt", "noun", lookup, has_senses=True) is None
    assert generate_en("luxury", "adjective", lookup).definition.text.startswith("relating to or typical of")


def test_no_template_means_no_definition():
    assert generate_en("zzzz", "noun", lookup) is None


def test_generated_text_never_contains_the_headword():
    def leaky(word, pos):
        return ("in a quickly manner", None)

    assert generate_en("quickly", "adverb", leaky) is None


def test_russian_templates():
    assert ru_adverb("быстрый") == "быстро"
    assert ru_adverb("тихий") == "тихо"
    ru = {("quick", "adjective"): ["быстрый"], ("happy", "adjective"): ["счастливый"]}
    lookup_ru = lambda w, p: ru.get((w, p), [])
    gen = generate_ru("quickly", "adverb", lookup_ru)
    assert gen.definition.text == "быстро" and gen.definition.lang == "ru" and gen.definition.source == "generated"
    assert generate_ru("unhappy", "adjective", lookup_ru).definition.text == "несчастливый"
    assert generate_ru("slowly", "adverb", lookup_ru) is None
