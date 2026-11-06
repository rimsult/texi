import json
import math

import pytest

from lexi_pipeline import gapfill
from lexi_pipeline.gapfill import (RULE, RULE_KEY, GapIndex, GapLM, find_gap, inflect, preferred_form,
                                   rejection_reason, word_forms)


def zipf(word):  # every real-looking form "exists"; lemminflect's OOV guesses do not
    return 0 if word.endswith(("uler", "fuller")) else 4


@pytest.mark.parametrize("lemma,pos,example,form,tag", [
    ("eat", "verb", "I have eaten an apple.", "eaten", "VBN"),
    ("eat", "verb", "We ate dinner at six.", "ate", "VBD"),
    ("walk", "verb", "He has walked a long way.", "walked", "VBN"),
    ("walk", "verb", "Yesterday we walked to the park.", "walked", "VBD"),
    ("walk", "verb", "She walks to school every day.", "walks", "VBZ"),
    ("put", "verb", "Please put the cup on the table.", "put", "VB"),
    ("look after", "verb", "She looked after her little sister.", "looked after", "VBD"),
    ("apple", "noun", "She bought three apples today.", "apples", "NNS"),
    ("child", "noun", "The children are playing outside.", "children", "NNS"),
    ("big", "adjective", "This house is bigger than mine.", "bigger", "JJR"),
    ("beautiful", "adjective", "This is the most beautiful place.", "beautiful", "JJ+"),
    ("dog", "noun", "Dogs like to play.", "Dogs", "NNS"),
])
def test_find_gap(entry, lemma, pos, example, form, tag):
    g = find_gap(entry("x", lemma, pos=pos, example=example))
    assert g is not None and (g.form, g.tag) == (form, tag)
    assert example[g.start:g.end] == form


@pytest.mark.parametrize("lemma,pos,example", [
    ("put", "verb", "He put the cup on the table."),  # base or past? ambiguous
    ("teach", "verb", "The teacher teaches maths."),  # "teacher" gives it away
    ("dog", "noun", "The dog chased another dog."),  # two occurrences
    ("dog", "noun", "Nice dog!"),  # too short
    ("cat", "noun", "The dog barked at the house."),  # not in the sentence
    ("quickly", "adverb", "He ran quickly to the bus."),  # adverbs fit almost anywhere
])
def test_find_gap_skips(entry, lemma, pos, example):
    assert find_gap(entry("x", lemma, pos=pos, example=example)) is None


def test_inflect_same_form(entry):
    g = find_gap(entry("x", "eat", pos="verb", example="I have eaten an apple."))
    assert inflect(entry("y", "drink", pos="verb"), g, zipf) == "drunk"
    assert inflect(entry("y", "sleep", pos="verb"), g, zipf) == "slept"
    adj = find_gap(entry("x", "big", pos="adjective", example="This house is bigger than mine."))
    assert inflect(entry("y", "small", pos="adjective"), adj, zipf) == "smaller"
    assert inflect(entry("y", "beautiful", pos="adjective"), adj, zipf) is None  # no "beautifuler"
    more = find_gap(entry("x", "beautiful", pos="adjective", example="This is the most beautiful place."))
    assert inflect(entry("y", "big", pos="adjective"), more, zipf) is None  # no "most big"
    assert inflect(entry("y", "expensive", pos="adjective"), more, zipf) == "expensive"
    cap = find_gap(entry("x", "dog", example="Dogs like to play."))
    assert inflect(entry("y", "table"), cap, zipf) == "Tables"


def test_plural_gap_forms(entry):
    bones = find_gap(entry("x", "bone", example="How many bones did a dinosaur have?"))
    assert bones.tag == "NNS"
    assert preferred_form("college", "noun", "NNS") == "colleges"  # not the uncountable "college"
    assert inflect(entry("y", "college"), bones, zipf) == "colleges"
    assert inflect(entry("y", "news"), bones, zipf) is None  # no distinct plural
    rare = lambda w: 2.7 if w == "informations" else 5.9  # noqa: E731
    assert inflect(entry("y", "information"), bones, rare) is None  # uncountable in practice


def test_word_forms_multiword_head():
    assert "looked after" in word_forms("look after", "verb")
    assert "ice creams" in word_forms("ice cream", "noun")


@pytest.fixture
def apple(entry):
    return entry("apple-n", "apple", group="noun.food", en="a round fruit", ru_terms={"яблоко"},
                 example="I ate an apple for lunch.", senses={"apple.n.01"})


@pytest.mark.parametrize("override,reason", [
    (dict(group="noun.food"), "same_semantic_group"),
    (dict(pos="verb"), "pos_mismatch"),
    (dict(level="B1"), "level_out_of_range"),
    (dict(senses={"apple.n.01"}), "shared_sense"),
    (dict(ru_terms={"яблоко"}), "shared_translation"),
    (dict(lemma="lunch", id="lunch-n"), "in_sentence"),
    (dict(lemma="ice hockey", id="ih-n"), "multiword"),
    (dict(lemma="goddamn", id="goddamn-n"), "sensitive_word"),
])
def test_gap_rejection_rules(entry, apple, override, reason):
    base = dict(id="idea-n", lemma="idea", group="noun.cognition", en="a thought", senses={"idea.n.01"})
    base.update(override)
    cand = entry(**base)
    assert rejection_reason(apple, cand, find_gap(apple)) == reason


def test_adjective_antonym_family_is_rejected(entry):
    hot = entry("hot-a", "hot", pos="adjective", group="adj:hot", hard_group="adjfam:cold.a.01",
                example="The soup is very hot today.")
    cold = entry("cold-a", "cold", pos="adjective", group="adj:cold", hard_group="adjfam:cold.a.01")
    assert rejection_reason(hot, cold, find_gap(hot)) == "same_semantic_group"


def test_lm_verdicts(tmp_path):
    lm = GapLM(tmp_path / "lm.json")
    key = "I ate an ___ for lunch."
    lm.data[key] = {"p": 0.44, "x": ["egg", "orange"], "ok": ["idea"]}
    assert lm.rejects(key, "Orange") and lm.verdict(key, "egg") is True
    assert not lm.rejects(key, "idea") and lm.verdict(key, "idea") is False
    assert lm.rejects(key, "river") and lm.verdict(key, "river") is None  # judged sentence, unjudged word
    assert not lm.rejects("unknown sentence ___.", "idea")  # the model never saw it: unchecked


def test_plausible_rule():
    lp = math.log
    common, rare = lp(1e-4), lp(1e-7)  # corpus frequencies
    assert GapLM.plausible(lp(0.5), common, lp(0.02), common)  # likely in the gap on its own
    assert not GapLM.plausible(lp(0.5), common, lp(0.0004), common)
    # a rare answer fits far better than a common word that is still quite likely there
    assert GapLM.plausible(lp(0.005), rare, lp(0.0001), common)
    assert not GapLM.plausible(lp(0.005), rare, lp(0.00001), common)
    # fit: a rare word slightly likely in the gap fits as well as a common answer
    assert GapLM.plausible(lp(0.5), common, lp(0.00001), rare)
    assert not GapLM.plausible(lp(0.5), common, lp(0.00001), common)


def _pool(entry):
    words = [("idea", "noun.cognition"), ("river", "noun.object"), ("song", "noun.communication"),
             ("chair", "noun.artifact"), ("orange", "noun.plant"), ("doctor", "noun.person")]
    return [entry(f"{w}-n", w, group=g, en=f"definition of {w}", senses={f"{w}.n.01"}) for w, g in words]


def test_build_question_forms_and_span(entry, apple, tmp_path):
    lm = GapLM(tmp_path / "lm.json")
    index = GapIndex([apple, *_pool(entry)], zipf, lm)
    (key, answer, forms), = index.lm_requests([apple])
    assert key == "I ate an ___ for lunch." and answer == "apple" and "orange" in forms
    lm.data[key] = {"p": 0.2, "x": ["orange"], "ok": [f for f in forms if f != "orange"]}
    assert index.lm_requests([apple]) == []  # every candidate judged
    q = index.build_question(apple)
    assert q.status == "ok" and q.trainer == "gap-fill" and q.lang == "en"
    assert q.span == [9, 14] and q.forms[0] == "apple"
    assert "orange-n" not in q.distractors and len(q.distractors) == len(q.forms) - 1 >= 2
    assert index.build_question(apple).distractors == q.distractors  # deterministic
    data = q.to_json()
    assert data["span"] == [9, 14] and data["forms"] == q.forms
    lm.data[key]["ok"] = ["song"]  # unjudged candidates of a judged sentence are not used
    assert GapIndex([apple, *_pool(entry)], zipf, lm).build_question(apple).forms == ["apple", "song"]


def test_insufficient_distractors(entry, apple):
    q = GapIndex([apple], zipf).build_question(apple)
    assert q.status == "needs_review" and q.reasons == ["insufficient_distractors"]


def test_lm_requests_stop_at_accept_limit(entry, apple, tmp_path, monkeypatch):
    monkeypatch.setattr(gapfill, "ACCEPT_LIMIT", 2)
    lm = GapLM(tmp_path / "lm.json")
    index = GapIndex([apple, *_pool(entry)], zipf, lm)
    (key, _, first), = index.lm_requests([apple])
    assert len(first) == 4  # about half of the unjudged ones are expected to pass
    lm.data[key] = {"p": 0.2, "x": first[:3], "ok": first[3:]}
    (_, _, more), = index.lm_requests([apple])
    assert more and not set(more) & set(first)  # the walk continues where the verdicts end


def test_walk_stops_at_max_tried(entry, apple, tmp_path, monkeypatch):
    monkeypatch.setattr(gapfill, "MAX_TRIED", 3)
    lm = GapLM(tmp_path / "lm.json")
    index = GapIndex([apple, *_pool(entry)], zipf, lm)
    (key, _, forms), = index.lm_requests([apple])
    assert len(forms) == 3
    lm.data[key] = {"p": 0.2, "x": forms[:2], "ok": forms[2:]}
    assert index.lm_requests([apple]) == []  # where nearly anything fits, the walk ends early
    q = index.build_question(apple)
    assert q.forms == ["apple", forms[2]] and q.status == "needs_review"


def test_fill_judges_with_scores(tmp_path, monkeypatch):
    lm = GapLM(tmp_path / "lm.json", model_dir=tmp_path)
    (tmp_path / "config.json").write_text("{}")
    key = "I ate an ___ for lunch."
    monkeypatch.setattr(lm, "score", lambda items, progress=None: [
        (math.log(0.3), {"orange": math.log(0.05), "river": math.log(1e-6), "antidisestablishment": None})])
    assert lm.fill([(key, "apple", ["Orange", "river", "antidisestablishment"])], zipf=lambda w: 4) == 1
    assert lm.get(key) == {"p": 0.3, "x": ["antidisestablishment", "orange"], "ok": ["river"]}
    assert lm.fill([(key, "apple", ["river"])]) == 0  # already judged
    assert lm.prune() == 3  # judging is not a lookup: nothing has walked these verdicts yet


def test_lm_cache_round_trip(tmp_path, entry, apple):
    lm = GapLM(tmp_path / "lm.json")  # no model: judging is a no-op
    lm.judge(GapIndex([apple, *_pool(entry)], zipf, lm), [apple])
    assert lm.data == {}
    lm.data["k ___"] = {"p": 0.1, "x": ["egg"], "ok": ["idea"]}
    lm.dirty = True
    lm.save()
    text = (tmp_path / "lm.json").read_text()
    assert text.count("\n") == 4  # a line per sentence
    data = json.loads(text)
    assert data[RULE_KEY] == RULE and data["k ___"] == {"p": 0.1, "x": ["egg"], "ok": ["idea"]}
    again = GapLM(tmp_path / "lm.json")
    assert again.get("k ___") == {"p": 0.1, "x": ["egg"], "ok": ["idea"]} and RULE_KEY not in again.data
    data[RULE_KEY] = "other thresholds"
    (tmp_path / "lm.json").write_text(json.dumps(data))
    assert GapLM(tmp_path / "lm.json").get("k ___") is None  # stale verdicts are dropped


LM_DIR = __import__("pathlib").Path(__file__).resolve().parents[1] / "raw" / "bert-base-uncased"


@pytest.mark.skipif(not (LM_DIR / "config.json").exists(), reason="BERT model not downloaded")
def test_real_model_rejects_fitting_words(tmp_path):
    lm = GapLM(tmp_path / "lm.json", model_dir=LM_DIR)
    key = "I ate an ___ for lunch."
    lm.fill([(key, "apple", ["orange", "egg", "river", "song", "idea"])])
    assert lm.rejects(key, "orange") and lm.rejects(key, "egg")
    assert not lm.rejects(key, "river") and not lm.rejects(key, "song")


def test_prune_keeps_only_verdicts_the_build_looked_up(tmp_path):
    lm = GapLM(tmp_path / "lm.json")
    lm.data = {"a ___": {"p": 0.1, "x": ["egg", "ham"], "ok": ["idea", "tree"]},
               "gone ___": {"p": 0.2, "x": ["cat"], "ok": []}}
    assert lm.rejects("a ___", "Egg") and not lm.rejects("a ___", "idea")
    assert lm.prune() == 3  # ham, tree and the whole unused sentence
    assert lm.data == {"a ___": {"p": 0.1, "x": ["egg"], "ok": ["idea"]}} and lm.dirty
    assert lm.rejects("a ___", "egg") and not lm.rejects("a ___", "idea")  # same answers after pruning
