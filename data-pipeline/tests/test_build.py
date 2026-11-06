"""End-to-end build on a tiny real dataset (real WordNet, fixture CEFR + Wiktionary)."""
import json

from lexi_pipeline.build import build, pick_synonyms
from lexi_pipeline.gapfill import GapLM
from lexi_pipeline.simple_wiktionary import SimpleEntry, SimpleSense, SimpleWiktionary
from lexi_pipeline.mt import TranslationCache

# A tiny stand-in for wordfreq: only these words are "frequent enough".
ZIPF = {"dog": 5.5, "cat": 5.2, "apple": 4.9, "table": 5.3, "water": 5.6, "mother": 5.4, "morning": 5.3,
        "happiness": 4.5, "car": 5.4, "song": 5.1, "run": 5.6, "eat": 5.4, "sleep": 5.1, "think": 6.0,
        "buy": 5.4, "big": 5.6, "happy": 5.5, "cold": 5.1, "red": 5.3, "quickly": 4.9, "often": 5.2,
        "colour": 4.8, "color": 5.0,
        "transistor": 3.3, "capacitor": 3.0, "resistor": 2.9, "algorithm": 4.1, "compiler": 3.4,
        "hydrogen": 4.2, "oxygen": 4.5, "nitrogen": 3.9, "helium": 3.6, "triangle": 4.1, "rectangle": 3.7,
        "hexagon": 3.0, "voltage": 3.9}


_CYR = str.maketrans("abcdefghijklmnopqrstuvwxyz", "абцдефгхийклмнопкрстуввксз")


def fake_mt(sources):
    """Stand-in for the offline model: a recognisable 'Russian' rendering of every input."""
    return [["перевод " + s.lower().translate(_CYR)] for s in sources]


def test_mini_build_produces_valid_packs(mini_raw, tmp_path):
    out, review = tmp_path / "packs", tmp_path / "review"
    cache = TranslationCache(tmp_path / "mt.json")
    report = build(mini_raw, out, review, zipf=lambda w: ZIPF.get(w.lower(), 0.0), cache=cache, backend=fake_mt,
                   lm=GapLM(tmp_path / "lm.json"))
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["schemaVersion"] == 2
    assert [d["id"] for d in manifest["decks"]] == ["general", "tech"]
    general, tech = manifest["decks"]
    assert [l["level"] for l in general["levels"]] == ["A1", "A2", "B1", "B2", "C1", "C2"]
    assert [l["file"] for l in tech["levels"]][:2] == ["tech-A1.json", "tech-A2.json"]
    assert set(manifest["fields"]) == {"it", "electrical", "physics", "math", "chemistry", "engineering"}

    a1 = json.loads((out / "A1.json").read_text())
    assert a1["deck"] == "general"
    ids = {e["id"] for e in a1["entries"]}
    assert {"dog-n", "run-v", "big-adj"} <= ids
    dog = next(e for e in a1["entries"] if e["id"] == "dog-n")
    assert {d["lang"] for d in dog["definitions"]} == {"en", "ru"}
    ru = next(d for d in dog["definitions"] if d["lang"] == "ru")
    assert ru["source"] == "machine" and ru["text"].startswith("перевод ")  # the definition, translated
    assert "собака" in dog["translation"]  # the short Wiktionary translation, shown after answering
    assert report["stats"]["ru_machine"] > 0 and (tmp_path / "mt.json").exists()
    assert any(q["lang"] == "ru" for q in a1["questions"])
    assert report["stats"]["skipped"] == 2
    skipped = json.loads((review / "skipped.json").read_text())
    assert {s["headword"] for s in skipped} == {"the", "in"}
    nr = json.loads((review / "needs_review.json").read_text())
    shipped = {(q["entryId"], q["trainer"], q["lang"]) for q in a1["questions"]}
    assert not shipped & {(q["entryId"], q["trainer"], q["lang"]) for q in nr}

    tech_entries = [e for lv in tech["levels"] for e in json.loads((out / lv["file"]).read_text())["entries"]]
    lemmas = {e["lemma"] for e in tech_entries}
    assert {"transistor", "hydrogen", "triangle"} <= lemmas, lemmas
    assert all(e["id"].startswith("tech:") and e["domain"] in manifest["fields"] for e in tech_entries)
    assert all(e["level"] in ("B1", "B2", "C1", "C2") for e in tech_entries)  # none of them is in the CEFR list
    by_lemma = {e["lemma"]: e for e in tech_entries}
    assert by_lemma["transistor"]["domain"] == "electrical"
    assert by_lemma["hydrogen"]["domain"] == "chemistry"
    assert by_lemma["triangle"]["domain"] == "math"
    lexicon = json.loads((review / "lexicon.json").read_text())
    assert {e["deck"] for e in lexicon} == {"general", "tech"}


SIMPLE = SimpleWiktionary({
    ("dog", "noun"): SimpleEntry("dog", "noun", [SimpleSense(
        0, "A dog is an animal that people keep as a pet. Dogs can bark.", ["My dog likes to play in the park."])]),
    ("run", "verb"): SimpleEntry("run", "verb", [SimpleSense(
        0, "If you run, you move very quickly on your feet.", ["I run to school every day."])]),
})


def test_mini_build_uses_learner_definitions_and_translates_examples(mini_raw, tmp_path):
    out, review = tmp_path / "packs", tmp_path / "review"
    report = build(mini_raw, out, review, zipf=lambda w: ZIPF.get(w.lower(), 0.0),
                   cache=TranslationCache(tmp_path / "mt.json"), backend=fake_mt, simple=SIMPLE,
                   lm=GapLM(tmp_path / "lm.json"))
    stats = report["stats"]
    assert stats["simple_used"] == 2 and stats["ru_examples"] >= 2
    a1 = {e["id"]: e for e in json.loads((out / "A1.json").read_text())["entries"]}
    dog, run = a1["dog-n"], a1["run-v"]
    # only the best definition per language ships
    assert [(d["lang"], d["source"]) for d in dog["definitions"]] == [("en", "simple"), ("ru", "machine")]
    # learner frames are rewritten into dictionary form; a part that cannot be rewritten is dropped
    assert dog["definitions"][0]["text"] == "an animal that people keep as a pet"
    ru = dog["definitions"][1]["text"]
    assert ru == "перевод ан анимал тхат пеопле кееп ас а пет"  # the rewritten definition, translated
    assert dog["example"] == "My dog likes to play in the park."
    assert dog["exampleRu"].startswith("перевод ")
    assert run["definitions"][0]["text"] == "to move very quickly on your feet"
    assert not any("___" in d["text"] for e in a1.values() for d in e["definitions"])
    # optional gap-fill trainer: the example with the word left out, options in the same form
    pack = json.loads((out / "A1.json").read_text())
    gap = next(q for q in pack["questions"] if q["trainer"] == "gap-fill" and q["entryId"] == "dog-n")
    assert gap["lang"] == "en" and dog["example"][slice(*gap["span"])] == "dog" == gap["forms"][0]
    assert len(gap["forms"]) == len(gap["distractors"]) + 1 >= 3
    assert stats["general:questions_gap_fill"] >= 1
    assert manifest_counts(out)["gap-fill:en"] >= 1
    adapt_log = json.loads((review / "adapt_log.json").read_text())
    assert {r["id"] for r in adapt_log if r["reason"] == "used"} == {"dog-n", "run-v"}

    manifest = json.loads((out / "manifest.json").read_text())
    assert any(s["name"].startswith("Simple English Wiktionary") for s in manifest["sources"])
    tech = next(d for d in manifest["decks"] if d["id"] == "tech")
    for lv in tech["levels"]:
        fields = lv.get("fields", {})
        assert set(fields) <= set(manifest["fields"])
        for key, n in lv["questions"].items():  # per-field counts add up to the level's counts
            assert sum(f["questions"].get(key, 0) for f in fields.values()) == n


def manifest_counts(out):
    manifest = json.loads((out / "manifest.json").read_text())
    return next(lv for lv in manifest["decks"][0]["levels"] if lv["level"] == "A1")["questions"]


def test_pick_synonyms_keeps_common_single_words(entry):
    e = entry("big-adj", "big", pos="adjective", synonyms={"big", "large", "bigger", "great", "full-size", "magnitudinous"})
    zipf = {"large": 5.4, "great": 5.8, "bigger": 4.9, "full-size": 3.5, "magnitudinous": 1.0}.get
    assert pick_synonyms(e, lambda w: zipf(w, 0.0)) == ["great", "large"]
