"""Offline machine translation of definitions: normalisation, checks, caching."""
import json

from lexi_pipeline.mt import (candidates, parts, TranslationCache, choose, chrf, deepl_backend, google_backend, normalize,
                              rejection, source_variants)


def test_source_variants_frame_glosses_by_part_of_speech():
    assert source_variants("make better", "verb") == ["to make better", "make better"]
    assert source_variants("to make better", "verb")[0] == "to make better"
    assert source_variants("having great size", "adjective") == ["with great size", "having great size"]
    assert source_variants("being in good health", "adjective")[0] == "in good health"
    assert source_variants("of or relating to the sea", "noun") == ["relating to the sea"]
    assert source_variants("in or at that place", "adverb") == ["in that place"]  # not «в или в том месте»
    assert source_variants("a place to sleep in or at night", "noun") == ["a place to sleep in or at night"]


def test_normalize_strips_model_filler():
    assert normalize("Чтобы добраться до места.") == "добраться до места"
    assert normalize("Это большое животное") == "большое животное"
    assert normalize("Что-то, что светит") == "светит"
    assert normalize("ДНК клетки") == "ДНК клетки"  # acronyms keep their case
    assert normalize("A несовершеннолетний подросток") == "несовершеннолетний подросток"


def test_rejection_rules():
    en = "a domesticated carnivorous mammal"
    assert rejection("одомашненное хищное млекопитающее", en) is None
    assert rejection("", en) == "empty"
    assert rejection("одомашненный mammal", en) == "untranslated"
    assert rejection("a животное", en) == "untranslated"
    assert rejection("12345", en) == "not_russian"
    assert rejection("силой или силой", "by force or violence") == "repeated_word"
    assert rejection("сила", en) == "length"
    # repetition is fine when the English repeats too
    assert rejection("состояние, похожее на состояние сна", "a state resembling the state of sleep") is None
    assert rejection("снова и снова; постоянно", "over and over again; constantly") is None
    assert rejection("если вы помогаете кому-то, вы помогаете ему", "if you aid someone, you help them") is None
    # …but two English synonyms rendered as one Russian word twice are not
    assert rejection("если что-то музыкальное, то это музыка или музыка", "if something is musical it makes music or is about music") == "repeated_word"
    assert rejection("в или в этом месте", "in or at this place") == "repeated_word"
    assert rejection("не более; не более; только", "no more than; no other than; just") == "repeated_word"
    # a candidate with such a double is repaired rather than lost
    assert candidates("to find something pleasant, enjoyable, or interesting", "verb",
                      {"argos": ["найти что-то приятное, приятное или интересное"]})[0][0] == "найти что-то приятное или интересное"
    assert candidates("over and over again", "adverb", {"argos": ["снова и снова"]})[0][0] == "снова и снова"
    # a man the English never mentions
    assert rejection("взрослый мужчина женского пола", "an adult female person") == "gender"
    assert rejection("взрослый человек женского пола", "an adult female person") is None


def test_choose_prefers_the_expected_shape_then_model_order():
    hyps = ["Улучшение", "Сделать лучше", "улучшить"]
    assert choose("make better", "verb", hyps) == "сделать лучше"
    assert choose("make better", "verb", ["ok"]) is None
    assert choose("a female parent", "noun", ["родитель женского пола", "мать-родитель"]) == "родитель женского пола"


def test_cache_translates_only_missing_items_and_persists(tmp_path):
    calls = []

    def backend(sources):
        calls.append(list(sources))
        table = {"a female parent": ["родитель женского пола"], "to make better": ["сделать лучше"],
                 "make better": ["улучшение"], "xyz": ["xyz"]}
        return [table.get(s, ["???"]) for s in sources]

    path = tmp_path / "mt.json"
    cache = TranslationCache(path)
    items = [("a female parent", "noun"), ("make better", "verb"), ("xyz", "noun"), ("a female parent", "noun")]
    assert cache.translate_missing(items, backend, batch=2) == 3
    assert cache.get("a female parent", "noun") == "родитель женского пола"
    assert cache.get("make better", "verb") == "сделать лучше"
    assert cache.has("xyz", "noun") and cache.get("xyz", "noun") is None  # rejected, remembered as null
    assert json.loads(path.read_text("utf-8"))["noun|a female parent"] == "родитель женского пола"

    again = TranslationCache(path)
    calls.clear()
    assert again.translate_missing(items, backend) == 0
    assert calls == []  # everything comes from the committed cache


def test_sentences_are_translated_as_sentences():
    assert source_variants("if you run, you go quickly", "verb") == ["If you run, you go quickly."]
    assert source_variants("She runs every morning.", "example") == ["She runs every morning."]
    assert normalize("Она бегает каждое утро.", sentence=True) == "Она бегает каждое утро."
    assert choose("She runs every morning.", "example", ["Она бегает каждое утро."]) == "Она бегает каждое утро."


def test_chrf_measures_agreement():
    assert chrf("сделать лучше", "сделать лучше") == 1.0
    assert chrf("сделать лучше", "Сделать лучше.") == 1.0
    assert chrf("сделать лучше", "улучшить") < chrf("сделать лучше", "делать лучше")
    assert chrf("кот", "") == 0.0


def test_consensus_beats_a_confident_hallucination():
    en = "the activity of sorting things"
    hyps = {"argos": ["занятие плаванием", "сортировка вещей"],
            "wmt19": ["сортировка предметов", "деятельность по сортировке"]}
    assert choose(en, "noun", hyps["argos"]) == "занятие плаванием"  # one engine: its first hypothesis
    assert choose(en, "noun", hyps).startswith("сортировка")  # two engines: the reading both share


def test_glossary_breaks_ties_between_engines():
    en = "a small animal that people keep as a pet"
    hyps = {"argos": ["маленький зверёк, которого держат дома"], "wmt19": ["маленькое животное, которое держат дома"]}
    assert choose(en, "noun", hyps, glossary=["животное"]) == "маленькое животное, которое держат дома"
    assert choose(en, "noun", hyps, glossary=["зверёк"]) == "маленький зверёк, которого держат дома"


def test_cache_combines_several_engines_with_glossary(tmp_path):
    seen = {}

    def engine(name, table):
        def run(sources):
            seen.setdefault(name, []).extend(sources)
            return [table.get(s, ["???"]) for s in sources]
        return run

    backends = {
        "argos": engine("argos", {"a young dog": ["молодой пёс", "щенок собаки"]}),
        "wmt19": engine("wmt19", {"a young dog": ["молодая собака"]}),
    }
    cache = TranslationCache(tmp_path / "mt.json")
    items = [("a young dog", "noun"), ("If you run, you go quickly.", "example")]
    assert cache.translate_missing(items, backends, glossary={("a young dog", "noun"): ["собака"]}) == 2
    assert seen["argos"] == seen["wmt19"] == ["a young dog", "If you run, you go quickly."]  # shortest first
    assert cache.get("a young dog", "noun") == "молодая собака"
    assert cache.has("If you run, you go quickly.", "example")


def test_ensemble_scores_override_agreement():
    en = "mildly acid red fruit eaten as a vegetable"
    hyps = {"argos": ["слегка кислые красные плоды, которые едят как овощ"],
            "wmt19": ["кислые красные плоды, съеденные в качестве", "кислые красные плоды, съедаемые в качестве"]}
    truncated = "кислые красные плоды, съеденные в качестве"
    scores = {"слегка кислые красные плоды, которые едят как овощ": -0.4 - 1.2,
              truncated: -1.6 - 0.8, "кислые красные плоды, съедаемые в качестве": -1.8 - 0.8}
    assert choose(en, "noun", hyps, scores=scores) == "слегка кислые красные плоды, которые едят как овощ"


def test_repeated_content_word_is_penalised():
    en = "Scientists have found other suns with planets around them."
    hyps = {"argos": ["Учёные нашли другие солнца с планетами вокруг них."],
            "wmt19": ["Учёные нашли другие планеты с планетами вокруг них."]}
    scores = {"Учёные нашли другие солнца с планетами вокруг них.": -1.47,
              "Учёные нашли другие планеты с планетами вокруг них.": -1.44}
    assert choose(en, "example", hyps, scores=scores) == "Учёные нашли другие солнца с планетами вокруг них."


def test_a_dropped_sentence_loses_even_with_a_better_score():
    en = "Please hand me that tool. I can't reach it."
    full, short = "Пожалуйста, передай мне этот инструмент. Я не могу до него дотянуться.", "Пожалуйста, передай мне этот инструмент."
    hyps = {"argos": [full], "wmt19": [short]}
    assert choose(en, "example", hyps, scores={full: -1.4, short: -1.1}) == full
    # …but when every candidate merged or lost a sentence, one is still chosen.
    assert choose(en, "example", {"argos": [short]}) == short
    assert parts(en) == 2 and parts("food, e.g. bread") == 1 and parts("a tool; it cuts") == 2


def test_a_definition_is_not_collapsed_into_one_word():
    hyps = {"argos": ["день после сегодняшнего дня", "послезавтра"], "wmt19": ["послезавтра"]}
    scores = {"день после сегодняшнего дня": -1.9, "послезавтра": -1.6}
    assert choose("day after today", "noun", hyps, scores=scores) == "день после сегодняшнего дня"
    assert choose("a very small dog", "noun", {"argos": ["маленькая собачка"], "wmt19": ["собачка"]}) == "маленькая собачка"
    assert choose("pet dog", "noun", {"argos": ["собака-компаньон"], "wmt19": ["домашняя собака"]},
                  scores={"собака-компаньон": -0.5, "домашняя собака": -0.9}) == "собака-компаньон"  # short source: no rule


def test_noun_definition_prefers_the_nominative():
    hyps = {"argos": ["скрытую или неизвестную информацию"], "wmt19": ["скрытая или неизвестная информация"]}
    scores = {"скрытую или неизвестную информацию": -1.00, "скрытая или неизвестная информация": -1.05}
    assert choose("hidden or unknown information", "noun", hyps, scores=scores) == "скрытая или неизвестная информация"


def test_cache_rescoring_asks_every_engine_about_every_candidate(tmp_path):
    asked = {}

    def engine(name, outputs, prefer):
        def run(sources):
            return [outputs for _ in sources]

        def score(sources, targets):
            asked.setdefault(name, set()).update(targets)
            return [-0.2 if t == prefer else -1.0 for t in targets]
        run.score = score
        return run

    backends = {"argos": engine("argos", ["день, следующий за сегодняшним"], "завтрашний день"),
                "wmt19": engine("wmt19", ["завтрашний день", "день после сегодня"], "завтрашний день")}
    cache = TranslationCache(tmp_path / "mt.json")
    assert cache.translate_missing([("day after today", "noun")], backends) == 1
    assert asked["argos"] == asked["wmt19"] == {"день, следующий за сегодняшним", "завтрашний день", "день после сегодня"}
    assert cache.get("day after today", "noun") == "завтрашний день"


def test_deepl_backend_posts_all_texts_in_one_request():
    sent = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"translations": [{"text": "собака"}, {"text": "кошка"}]}).encode()

    def opener(req):
        sent["url"], sent["auth"], sent["body"] = req.full_url, req.get_header("Authorization"), req.data.decode()
        return Resp()

    run = deepl_backend("abc:fx", opener)
    assert run(["dog", "cat"]) == [["собака"], ["кошка"]]
    assert sent["url"] == "https://api-free.deepl.com/v2/translate"
    assert sent["auth"] == "DeepL-Auth-Key abc:fx"
    assert "text=dog" in sent["body"] and "text=cat" in sent["body"] and "target_lang=RU" in sent["body"]


def test_google_backend_posts_json_and_unescapes():
    sent = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"data": {"translations": [{"translatedText": "собака"},
                                                         {"translatedText": "кот &amp; кошка"}]}}).encode()

    def opener(req):
        sent["url"], sent["type"], sent["body"] = req.full_url, req.get_header("Content-type"), json.loads(req.data)
        return Resp()

    run = google_backend("k123", opener)
    assert run(["dog", "cat"]) == [["собака"], ["кот & кошка"]]
    assert sent["url"] == "https://translation.googleapis.com/language/translate/v2?key=k123"
    assert sent["type"] == "application/json"
    assert sent["body"] == {"q": ["dog", "cat"], "source": "en", "target": "ru", "format": "text"}


def test_api_engines_are_optional(monkeypatch):
    from lexi_pipeline import mt

    monkeypatch.delenv("DEEPL_AUTH_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_TRANSLATE_API_KEY", raising=False)
    monkeypatch.setattr(mt, "model_dir", lambda: None)
    monkeypatch.setattr(mt, "fsmt_dir", lambda: None)
    assert mt.available_backends() == {}
    monkeypatch.setenv("GOOGLE_TRANSLATE_API_KEY", "k")
    assert set(mt.available_backends()) == {"google"}
