"""Strict template-based definition generation.

Used only when no dictionary definition exists. Templates derive a definition
from the *dictionary article of a base word* (never from free text), so every
generated definition is traceable. All results carry source="generated" and a
quality strictly below any dictionary source.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .models import QUALITY, Definition
from .text import leaks

# lookup(word, pos) -> (clean gloss, base synset-like object) | None
Lookup = Callable[[str, str], "tuple[str, object] | None"]


@dataclass
class Generated:
    definition: Definition
    base_word: str
    base_pos: str
    base_ref: object  # base synset, used to inherit the semantic group
    rule: str


def _adv_bases(word: str) -> list[str]:
    if word.endswith("ily"):
        return [word[:-3] + "y"]
    if word.endswith("ally"):
        return [word[:-4], word[:-2]]
    if word.endswith("ly"):
        return [word[:-2], word[:-2] + "e"]
    return []


def _agent_bases(word: str) -> list[str]:
    out = []
    for suf in ("er", "or"):
        if word.endswith(suf):
            stem = word[: -len(suf)]
            out += [stem, stem + "e"]
            if len(stem) > 2 and stem[-1] == stem[-2]:
                out.append(stem[:-1])
    return out


# (rule, target pos, base candidates, base pos, template, is_conversion)
# Conversion rules (same spelling, different POS) are only allowed for true
# lexical gaps: when the word has no dictionary sense at all for that POS.
RULES: list[tuple[str, str, Callable[[str], list[str]], str, str, bool]] = [
    ("adverb_from_adjective", "adverb", _adv_bases, "adjective", "in a way that is {gloss}", False),
    ("negated_adjective", "adjective",
     lambda w: [w[len(p):] for p in ("un", "dis", "non", "in", "im", "il", "ir") if w.startswith(p)],
     "adjective", "not {gloss}", False),
    ("quality_noun", "noun",
     lambda w: ([w[:-5] + "y"] if w.endswith("iness") else []) + ([w[:-4]] if w.endswith("ness") else []),
     "adjective", "the quality or state of being {gloss}", False),
    ("agent_noun", "noun", _agent_bases, "verb", "a person or thing whose job or purpose is to {gloss}", False),
    ("noun_from_verb", "noun", lambda w: [w], "verb", "an act or result of the action: to {gloss}", True),
    ("adjective_from_noun", "adjective", lambda w: [w], "noun", "relating to or typical of {gloss}", True),
]


def generate_en(lemma: str, pos: str, lookup: Lookup, has_senses: bool = False) -> Generated | None:
    word = lemma.lower()
    for rule, target_pos, bases, base_pos, template, conversion in RULES:
        if pos != target_pos or (conversion and has_senses):
            continue
        for base in bases(word):
            if len(base) < 3:
                continue
            found = lookup(base, base_pos)
            if not found:
                continue
            gloss, ref = found
            text = template.format(gloss=gloss)
            if leaks(text, [lemma]) or len(text.split()) > 26:
                continue
            return Generated(Definition(text, "en", "generated", QUALITY["generated_en"]), base, base_pos, ref, rule)
    return None


_ADJ_ENDINGS = (("ний", "не"), ("ый", "о"), ("ий", "о"), ("ой", "о"))


def ru_adverb(adj: str) -> str | None:
    for end, repl in _ADJ_ENDINGS:
        if adj.endswith(end) and len(adj) > len(end) + 2:
            return adj[: -len(end)] + repl
    return None


def generate_ru(lemma: str, pos: str, ru_lookup: Callable[[str, str], list[str]]) -> Generated | None:
    """Russian definition by template from the base word's Wiktionary translation."""
    word = lemma.lower()
    if pos == "adverb":
        for base in _adv_bases(word):
            terms = [t for t in (ru_adverb(x) for x in ru_lookup(base, "adjective")) if t]
            if terms:
                d = Definition(", ".join(terms[:2]), "ru", "generated", QUALITY["generated_ru"])
                return Generated(d, base, "adjective", None, "ru_adverb_from_adjective")
    if pos == "adjective":
        for p in ("un", "dis", "in", "im"):
            if word.startswith(p):
                terms = [t for t in ru_lookup(word[len(p):], "adjective") if " " not in t]
                if terms:
                    d = Definition(", ".join("не" + t for t in terms[:2]), "ru", "generated", QUALITY["generated_ru"])
                    return Generated(d, word[len(p):], "adjective", None, "ru_negated_adjective")
    return None
