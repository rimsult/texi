import pytest

from lexi_pipeline.distractors import MIN_DISTRACTORS, DistractorIndex, rejection_reason
from lexi_pipeline.models import allowed_langs

W2D, D2W = "word-to-definition", "definition-to-word"


@pytest.fixture
def dog(entry):
    return entry("dog-n", "dog", en="a domesticated carnivorous mammal", ru="собака", ru_terms={"собака", "пёс"})


@pytest.mark.parametrize("override,reason", [
    (dict(pos="verb"), "pos_mismatch"),
    (dict(level="B1"), "level_out_of_range"),
    (dict(group="noun.animal"), "same_semantic_group"),
    (dict(group=None), "unknown_semantic_group"),
    (dict(senses={"dog.n.01"}), "shared_sense"),
    (dict(synonyms={"dog", "hound"}), "synonym"),
    (dict(ru_terms={"пёс"}), "shared_translation"),
    (dict(lemma="idiot", id="idiot-n"), "sensitive_word"),
])
def test_each_rule_rejects(entry, dog, override, reason):
    base = dict(id="table-n", lemma="table", group="noun.artifact", en="a piece of furniture with a flat top",
                ru="стол", ru_terms={"стол"})
    base.update(override)
    cand = entry(**{**base, "senses": base.pop("senses", {"table.n.01"})})
    assert rejection_reason(dog, cand, W2D, "en") == reason


def test_valid_distractor_and_level_tolerance(entry, dog):
    for level in ("A1", "A2"):
        table = entry("table-n", "table", level=level, group="noun.artifact", en="a piece of furniture", ru="стол")
        assert rejection_reason(dog, table, W2D, "en") is None
        assert rejection_reason(dog, table, D2W, "ru") is None


def test_definition_rules_per_trainer(entry, dog):
    kennel = entry("kennel-n", "kennel", group="noun.artifact", en="a shelter for a dog")
    assert rejection_reason(dog, kennel, W2D, "en") == "definition_mentions_target"
    no_ru = entry("table-n", "table", group="noun.artifact", en="a piece of furniture")
    assert rejection_reason(dog, no_ru, W2D, "ru") == "no_definition_in_lang"
    assert rejection_reason(dog, no_ru, D2W, "ru") == "no_definition_in_lang"  # the client re-checks it too
    same = entry("x-n", "x", group="noun.artifact", en="A domesticated carnivorous mammal")
    assert rejection_reason(dog, same, W2D, "en") == "duplicate_definition"
    puppy = entry("puppy-n", "puppy", en="a young dog")
    assert rejection_reason(puppy, entry("dog2-n", "dog", group="noun.food", en="hot dog"), D2W, "en") in (
        "candidate_in_definition", "same_word")
    mammal = entry("mammal-n", "mammal", group="noun.food", en="warm-blooded animal")
    assert rejection_reason(dog, mammal, D2W, "en") == "candidate_in_definition"


def test_similarity_guard(entry, dog):
    cand = entry("wolf-n", "wolf", group="noun.object", en="a wild carnivorous mammal of the forest")
    assert rejection_reason(dog, cand, W2D, "en", similarity=lambda a, b: 0.9) == "too_similar"
    assert rejection_reason(dog, cand, W2D, "en", similarity=lambda a, b: 0.3) is None


def _world(entry):
    groups = ["noun.artifact", "noun.food", "noun.time", "noun.person", "noun.act", "noun.feeling"]
    items = [entry(f"w{i}-n", f"word{i}", group=g, en=f"definition number {i} about things", ru=f"слово{i}")
             for i, g in enumerate(groups)]
    return items


def test_question_ok_with_enough_distractors_and_deterministic(entry, dog):
    index = DistractorIndex([dog, *_world(entry)])
    q1 = index.build_question(dog, W2D, "en")
    q2 = DistractorIndex([dog, *_world(entry)]).build_question(dog, W2D, "en")
    assert q1.status == "ok" and len(q1.distractors) >= MIN_DISTRACTORS
    assert q1.distractors == q2.distractors
    assert "dog-n" not in q1.distractors


def test_needs_review_when_distractors_are_insufficient(entry, dog):
    # Only same-group candidates exist -> cannot build a safe question.
    cat = entry("cat-n", "cat", en="a small domesticated feline", ru="кошка")
    index = DistractorIndex([dog, cat])
    q = index.build_question(dog, W2D, "en")
    assert q.status == "needs_review" and q.reasons == ["insufficient_distractors"]


def test_needs_review_for_missing_definition_or_group(entry):
    index = DistractorIndex([])
    nodef = entry("x-n", "x")
    assert index.build_question(nodef, W2D, "en").reasons == ["no_definition"]
    nogroup = entry("y-n", "y", group=None, en="something")
    assert "unknown_semantic_group" in index.build_question(nogroup, W2D, "en").reasons


def test_russian_is_never_used_from_b1(entry):
    b1 = entry("idea-n", "idea", level="B1", en="a thought", ru="идея")
    q = DistractorIndex([b1]).build_question(b1, W2D, "ru")
    assert q.status == "needs_review" and "lang_not_allowed_for_level" in q.reasons
    assert allowed_langs("A1") == ("ru", "en") and allowed_langs("A2") == ("ru", "en")
    assert all(allowed_langs(l) == ("en",) for l in ("B1", "B2", "C1", "C2"))


def test_word_to_definition_pool_prefers_similar_length(entry, dog):
    short = entry("a-n", "aa", group="noun.food", en="a domesticated small fruit tree")
    long = entry("b-n", "bb", group="noun.time",
                 en="an extremely long and verbose definition that goes on and on about many unrelated matters")
    mid = entry("c-n", "cc", group="noun.act", en="a carnivorous kind of activity done")
    pool = DistractorIndex([dog, short, long, mid]).pool(dog, W2D, "en")
    assert pool[-1].id == "b-n"


# ---------------------------------------------------------------- hard mode
from lexi_pipeline.distractors import HARD_SIMILARITY_LIMIT_VERB, hard_rejection_reason  # noqa: E402


@pytest.fixture
def lunch(entry):
    return entry("lunch-n", "lunch", group="noun.food", hard_group="noun.food", en="a midday meal", ru="обед",
                 ru_terms={"обед"}, senses={"lunch.n.01"}, synset="lunch.n.01",
                 ancestors={"lunch.n.01", "meal.n.01", "food.n.02"})


def food(entry, id, lemma, **kw):
    base = dict(group="noun.food", hard_group="noun.food", en=f"the {lemma} meal of the day", ru=lemma,
                ru_terms={lemma}, senses={f"{lemma}.n.01"}, synset=f"{lemma}.n.01",
                ancestors={f"{lemma}.n.01", "meal.n.01", "food.n.02"})
    base.update(kw)
    return entry(id, lemma, **base)


def test_hard_mode_accepts_close_but_distinct_concepts(entry, lunch):
    dinner = food(entry, "dinner-n", "dinner", en="the main meal of the day served in the evening")
    assert hard_rejection_reason(lunch, dinner, "en") is None
    assert hard_rejection_reason(lunch, dinner, "ru") is None


@pytest.mark.parametrize("override,reason", [
    (dict(hard_group="noun.artifact", group="noun.artifact"), "different_semantic_group"),
    (dict(hard_group=None), "unknown_semantic_group"),
    (dict(pos="verb"), "pos_mismatch"),
    (dict(level="B1"), "level_out_of_range"),
    (dict(senses={"lunch.n.01", "dinner.n.01"}), "shared_sense"),
    (dict(synonyms={"dinner", "lunch"}), "synonym"),
    (dict(ru_all={"обед"}), "shared_translation"),  # «обед» = lunch *and* dinner: two right answers
    (dict(synset="meal.n.01", senses={"meal.n.01"}), "hypernym_relation"),  # lunch is a meal
    (dict(en="a midday meal"), "duplicate_definition"),
    (dict(en="a meal eaten after lunch"), "definition_mentions_target"),
])
def test_each_hard_rule_rejects(entry, lunch, override, reason):
    cand = food(entry, "dinner-n", "dinner", **override)
    assert hard_rejection_reason(lunch, cand, "en") == reason


def test_hyponym_of_target_is_rejected(entry, lunch):
    brunch = food(entry, "brunch-n", "brunch", ancestors={"brunch.n.01", "lunch.n.01", "meal.n.01"})
    assert hard_rejection_reason(lunch, brunch, "en") == "hypernym_relation"


def test_adjective_cluster_satellites_are_near_synonyms(entry):
    big = entry("big-adj", "big", pos="adjective", group="adj:large.a.01", hard_group="adjfam:large.a.01",
                en="above average in size", senses={"large.a.01"})
    huge = entry("huge-adj", "huge", pos="adjective", group="adj:large.a.01", hard_group="adjfam:large.a.01",
                 en="unusually great in size", senses={"huge.s.01"})
    small = entry("small-adj", "small", pos="adjective", group="adj:small.a.01", hard_group="adjfam:large.a.01",
                  en="limited in size", senses={"small.a.01"})
    assert hard_rejection_reason(big, huge, "en") == "same_cluster"
    assert hard_rejection_reason(big, small, "en") is None


def test_hard_similarity_limit_is_stricter_for_verbs(entry):
    def verb(id, lemma, en):
        return entry(id, lemma, pos="verb", group="verb.communication", hard_group="verb.communication", en=en,
                     senses={f"{lemma}.v.01"}, synset=f"{lemma}.v.01")
    blame, scold = verb("blame-v", "blame", "harass with constant criticism"), verb("scold-v", "scold", "censure severely")
    sim = lambda a, b: HARD_SIMILARITY_LIMIT_VERB + 0.01  # noqa: E731
    assert hard_rejection_reason(blame, scold, "en", sim) == "too_similar"
    noun_a, noun_b = food(entry, "a-n", "breakfast"), food(entry, "b-n", "supper")
    assert hard_rejection_reason(noun_a, noun_b, "en", sim) is None


def test_hard_pool_is_ranked_deduplicated_and_deterministic(entry, lunch):
    dinner = food(entry, "dinner-n", "dinner", en="the main meal of the day")
    supper = food(entry, "supper-n", "supper", en="a light evening meal")
    breakfast = food(entry, "breakfast-n", "breakfast", en="the first meal of the day")
    # same synset as breakfast: a second option with the same meaning must not appear
    brekkie = food(entry, "brekkie-n", "brekkie", en="the first meal of the day", synset="breakfast.n.01",
                   senses={"breakfast.n.01"})
    breakfast.senses = {"breakfast.n.01"}
    breakfast.synset = "breakfast.n.01"
    other = entry("table-n", "table", group="noun.artifact", hard_group="noun.artifact", en="furniture")
    rank = {"dinner-n": 0.9, "supper-n": 0.8, "breakfast-n": 0.85, "brekkie-n": 0.84}
    idx = DistractorIndex([lunch, dinner, supper, breakfast, brekkie, other],
                          rank=lambda a, b: rank.get(b.id, 0.0))
    pool = [e.id for e in idx.hard_pool(lunch, "en")]
    assert pool == ["dinner-n", "breakfast-n", "supper-n"]
    assert pool == [e.id for e in idx.hard_pool(lunch, "en")]
    assert idx.hard_pool(other, "en") == []  # nobody else in its group -> no hard question


# ---------------------------------------------------------------- Russian (translated definitions)
def test_russian_definition_must_not_name_the_target(entry, dog):
    """Translated definitions can contain translations: «молодая собака» (puppy) next to
    "dog" would give the answer away (w → d) or make two options right (d → w)."""
    puppy = entry("puppy-n", "puppy", group="noun.person", en="a young domestic animal",
                  ru="молодая собака", ru_terms={"щенок"})
    assert rejection_reason(dog, puppy, W2D, "ru") == "ru_definition_mentions_translation"
    assert rejection_reason(puppy, dog, D2W, "ru") == "ru_definition_mentions_translation"
    assert rejection_reason(dog, puppy, W2D, "en") is None  # English definitions are unaffected
    cat = entry("cat-n", "cat", group="noun.person", en="a small domesticated feline", ru="маленькое домашнее животное",
                ru_terms={"кошка"})
    assert rejection_reason(dog, cat, W2D, "ru") is None


def test_hard_mode_checks_translations_in_russian_definitions(entry, lunch):
    snack = food(entry, "snack-n", "snack", en="a light informal meal", ru="лёгкий обед на ходу", ru_terms={"перекус"})
    assert hard_rejection_reason(lunch, snack, "ru") == "ru_definition_mentions_translation"
    assert hard_rejection_reason(lunch, snack, "en") is None


def test_candidate_order_is_stable_when_the_word_list_changes(entry):
    from lexi_pipeline.models import stable_order
    words = [entry(f"w{i}-n", f"w{i}") for i in range(40)]
    before = [e.id for e in stable_order(words, "dog-n|word-to-definition|en")]
    after = [e.id for e in stable_order(words[:10] + [entry("new-n", "new")] + words[10:], "dog-n|word-to-definition|en")]
    assert [i for i in after if i != "new-n"] == before  # a new word only slots in
    assert before != [e.id for e in stable_order(words, "cat-n|word-to-definition|en")]  # per question
