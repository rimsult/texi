"""Learner definitions in dictionary form: the Cobuild frame ("If you X…, you…") without the word."""
import pytest

from lexi_pipeline.rewrite import BLANK, rewrite

B = BLANK


@pytest.mark.parametrize("text,pos,expected", [
    # verbs → infinitive, the object comes back in place of "it"
    (f"if you {B} something, you lift it up and move it to another place", "verb",
     "to lift something up and move it to another place"),
    (f"if a person {B} someone or something, they do not like someone or something", "verb",
     "not to like someone or something"),
    (f"if something {B}, it makes a sound like a bee flying", "verb", "to make a sound like a bee flying"),
    (f"if you {B} something, usually food, you put it in your mouth, chew it, and swallow it", "verb",
     "to put something in your mouth, chew it, and swallow it"),
    (f"if a person {B} somewhere, they live there", "verb", "to live somewhere"),
    (f"if you {B} an action, you do it", "verb", "to do an action"),
    (f"if something {B} something else such as a city, it partly or completely destroys it", "verb",
     "to partly or completely destroy something"),
    (f"to {B} something is to make it happen", "verb", "to make something happen"),
    (f"to {B} means to go in different directions", "verb", "to go in different directions"),
    # adjectives → the predicate, or "someone who / something that"
    (f"when something is {B}, it is not easy", "adjective", "not easy"),
    (f"when someone is {B}, the person is not friendly and is mean", "adjective", "not friendly and mean"),
    (f"if someone is {B}, they know how to do it", "adjective", "someone who knows how to do it"),
    (f"if something is {B}, then it probably will not happen", "adjective", "something that probably will not happen"),
    (f"if something is {B}, its temperature is between warm and cold", "adjective",
     "something whose temperature is between warm and cold"),
    (f"something that is {B} has no mistakes", "adjective", "something that has no mistakes"),
    (f"a {B} person is someone who is not sick", "adjective", "someone who is not sick"),
    (f"the {B} thing is the last one", "adjective", "the last one"),
    (f"someone is {B} if they are sure", "adjective", "sure"),
    (f"if something is {B}, it's good and people like it", "adjective", "good and people like it"),
    (f"if something is {B}, people like to look at it", "adjective", "something that people like to look at"),
    # adverbs → what is left after the repeated verb
    (f"if something is done {B}, it is done with a lot of noise", "adverb", "with a lot of noise"),
    (f"if something {B} happens, it happens at all times", "adverb", "at all times"),
    (f"you use {B} to add surprising information", "adverb", "used to add surprising information"),
    # nouns
    (f"the {B} of something is the place where the thing is", "noun", "the place where the thing is"),
    (f"a {B} is when you are not polite to someone", "noun", "when you are not polite to someone"),
    (f"{B} is what we measure with a clock", "noun", "what we measure with a clock"),
    (f"when you have {B}, you feel hungry", "noun", "what you have when you feel hungry"),
    (f"{B}, such as shirts, pants, socks, etc. are things that people wear", "noun",
     "things that people wear, such as shirts, pants, socks, etc."),
    (f"a {B} the act of asking for something", "noun", "the act of asking for something"),
    (f"{B} refers to the traits that make you different", "noun", "the traits that make you different"),
    (f"a {B} problem, issue or other thing is about money or business", "adjective", "about money or business"),
])
def test_rewrites(text, pos, expected):
    assert rewrite(text, pos) == expected


@pytest.mark.parametrize("text,pos", [
    (f"if you {B} something, you clean it with a {B}", "verb"),  # still needs the word
    (f"if you {B} something it belongs to you, it is yours", "verb"),  # main clause is about the thing
    (f"if you are {B} with something, it is not as good as you think", "adjective"),
    (f"if you {B}, your head and whole body are at the same level", "verb"),
    (f"if you {B} something, you will see it", "verb"),  # no infinitive for "will"
])
def test_no_rewrite_when_the_meaning_would_change(text, pos):
    assert rewrite(text, pos) is None


def test_text_without_the_word_is_kept():
    assert rewrite("a vehicle with two wheels", "noun") == "a vehicle with two wheels"
