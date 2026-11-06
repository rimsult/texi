"""Simple English Wiktionary: learner glosses → option texts that never show the headword."""
import gzip
import json

from lexi_pipeline.simple_wiktionary import (BLANK, SimpleSense, SimpleWiktionary, head_forms, learner_definition,
                                             learner_example)


def test_definition_drops_the_headword_frame_and_joins_sentences():
    gloss = "A bicycle is a vehicle with two wheels. You use your legs to make it move."
    assert learner_definition(gloss, "bicycle") == "a vehicle with two wheels; you use your legs to make it move"
    assert learner_definition("Happy means feeling good.", "happy") == "feeling good"
    assert learner_definition("The word cold means not warm at all.", "cold") == "not warm at all"
    assert learner_definition("Apples are a kind of round fruit (red or green).", "apple") == "a kind of round fruit"
    assert learner_definition("In law, a sentence is the punishment that a judge gives to a criminal.", "sentence") \
        == "the punishment that a judge gives to a criminal"


def test_frames_that_use_the_word_are_rewritten_without_it():
    # "If you run, you go quickly…" used to become "if you ___, you go quickly…": a gap-fill
    # question in disguise. The frame is rewritten into dictionary form instead.
    text = learner_definition("If you run, you go quickly on your feet. Running is faster than walking.", "run",
                              {"ran"}, pos="verb")
    assert text == "to go quickly on your feet"  # the aside that needs the word is dropped
    assert BLANK not in text
    assert learner_definition("If you carry something, you lift it up and move it to another place.", "carry",
                              pos="verb") == "to lift something up and move it to another place"
    assert learner_definition("When something is difficult, it is not easy.", "difficult", pos="adjective") \
        == "not easy"
    assert learner_definition("A hundredth of a meter; 100 centimeters is one meter.", "centimeter",
                              {"centimeters"}, pos="noun") == "a hundredth of a meter"


def test_you_use_x_to_becomes_used_to():
    assert learner_definition("You use sir to speak to a man politely.", "sir", pos="noun") \
        == "used to speak to a man politely"


def test_without_a_rewrite_there_is_no_learner_definition():
    # the entry then keeps its WordNet gloss (adapt.py)
    assert learner_definition("If you lie down, your head and whole body are at the same level.", "lie",
                              pos="verb") is None
    assert learner_definition("If you run, you go quickly on your feet.", "run") is None  # POS unknown


def test_long_glosses_keep_whole_sentences_only():
    gloss = "A dog is an animal that people keep as a pet. " + "It " + "barks and " * 20 + "runs."
    assert learner_definition(gloss, "dog") == "an animal that people keep as a pet"


def test_unusable_glosses_are_rejected():
    assert learner_definition("Plural of mouse.", "mice") is None
    assert learner_definition("Past tense of run.", "ran") is None
    assert learner_definition("The comparative form of good; more good.", "better", {"good"}) is None
    assert learner_definition("To be happy.", "happy", pos="adjective") is None  # nothing left but the word
    assert learner_definition("Lucky.", "fortunate") is None
    assert learner_definition("Am is another way of spelling a.m..", "am") is None  # also behind the frame
    assert learner_definition("great fear", "terror") == "great fear"


def test_head_forms_cover_regular_inflections():
    assert {"stop", "stops", "stopped", "stopping"} <= head_forms("stop")
    assert {"carry", "carries", "carried"} <= head_forms("carry")
    assert {"make", "making"} <= head_forms("make")
    assert "went" in head_forms("go", {"went"})


def test_example_must_use_the_word_and_be_short():
    sense = SimpleSense(0, "x", examples=["a lowercase start", "This is not about it at all.",
                                          "Every single morning before work she runs in the park",
                                          "She runs every morning"])
    assert learner_example(sense, "run") == "She runs every morning."  # the shortest good one
    assert learner_example(SimpleSense(0, "x", examples=["Run!"]), "run") is None


def test_load_merges_etymologies_and_filters_words(tmp_path):
    rows = [
        {"word": "bat", "pos": "noun", "senses": [{"glosses": ["A bat is a stick used to hit a ball."],
                                                    "examples": [{"text": "He swung the bat."}]}],
         "forms": [{"form": "bats"}]},
        {"word": "bat", "pos": "noun", "senses": [{"glosses": ["A bat is a small animal that flies at night."],
                                                    "tags": ["informal"]}]},
        {"word": "bat", "pos": "verb", "senses": [{"glosses": ["If you bat, you hit a ball."]}]},
        {"word": "cat", "pos": "noun", "senses": [{"glosses": ["A cat is a small pet."]}]},
        {"word": "bat", "pos": "name", "senses": [{"glosses": ["A name."]}]},
        {"word": "bat", "pos": "noun", "senses": [{"glosses": ["A rude word."], "tags": ["vulgar"]}]},
    ]
    path = tmp_path / "simple.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write("\n".join(json.dumps(r) for r in rows) + "\n")
    simple = SimpleWiktionary.load(path, wanted={"bat"})
    assert len(simple) == 2 and simple.get("cat", "noun") is None
    bat = simple.get("Bat", "noun")
    assert [s.index for s in bat.senses] == [0, 1, 2]
    assert bat.senses[0].examples == ["He swung the bat."] and "bats" in bat.forms
    assert bat.senses[1].tags == ["informal"] and not bat.senses[1].skipped
    assert bat.senses[2].skipped
    assert simple.get("bat", "verb").senses[0].gloss == "If you bat, you hit a ball."
