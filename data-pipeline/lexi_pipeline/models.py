from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Literal

LEVELS: tuple[str, ...] = ("A1", "A2", "B1", "B2", "C1", "C2")
DECKS: tuple[str, ...] = ("general", "tech")
Lang = Literal["en", "ru"]
Source = Literal["wordnet", "simple", "wiktionary", "generated", "machine"]

# Lower quality for generated definitions is a hard rule: any dictionary
# definition must always outrank a generated one.
QUALITY: dict[str, float] = {
    "simple": 0.95,  # Simple English Wiktionary learner definition (chosen per level, see adapt.py)
    "wordnet": 0.9,
    "wiktionary": 0.8,
    "wiktionary_gloss": 0.7,
    "machine": 0.7,  # offline machine translation of a dictionary definition (ru)
    "generated_en": 0.5,
    "generated_ru": 0.4,
}
MAX_GENERATED_QUALITY = 0.5

POS_TO_WN = {"noun": "n", "verb": "v", "adjective": "a", "adverb": "r"}
SUPPORTED_POS = tuple(POS_TO_WN)


def level_index(level: str) -> int:
    return LEVELS.index(level)


def allowed_langs(level: str) -> tuple[str, ...]:
    """A1–A2 may use Russian definitions; B1+ must be English only."""
    return ("ru", "en") if level_index(level) <= 1 else ("en",)


@dataclass
class Definition:
    text: str
    lang: str
    source: str
    quality: float

    def to_json(self) -> dict:
        return asdict(self)


@dataclass
class Entry:
    id: str
    lemma: str
    pos: str
    level: str
    variants: list[str] = field(default_factory=list)
    group: str | None = None  # semantic group
    senses: set[str] = field(default_factory=set)  # all WordNet synset ids of lemma+pos
    top_senses: list[str] = field(default_factory=list)  # most frequent senses first (≤ 6)
    synonyms: set[str] = field(default_factory=set)
    ru_terms: set[str] = field(default_factory=set)
    definitions: list[Definition] = field(default_factory=list)
    example: str | None = None
    synset: str | None = None  # chosen synset id, if any
    # Hard mode: distractors come from the *same* group. For nouns/verbs this is the
    # lexicographer file (= group); adjectives use the antonym family of their cluster.
    hard_group: str | None = None
    ancestors: set[str] = field(default_factory=set)  # hypernym closure of the chosen synset
    ru_all: set[str] = field(default_factory=set)  # translations of every sense (near-synonym check)
    deck: str = "general"
    domain: str | None = None  # technical field for the tech deck (it, electrical, physics, …)
    level_source: str = "cefr"  # "cefr" or "frequency" (estimated)
    translation: str | None = None  # short Russian translation (Wiktionary), shown after answering
    mt_source: str | None = None  # unmasked English text to machine-translate (simple definitions)
    sense_changed: bool = False  # adapt.py moved the entry to the sense of its learner definition
    example_ru: str | None = None  # machine translation of the example (A1–A2)
    see_also: list[str] = field(default_factory=list)  # common synonyms, shown after answering

    def best_definition(self, lang: str) -> Definition | None:
        defs = [d for d in self.definitions if d.lang == lang]
        return max(defs, key=lambda d: d.quality) if defs else None

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "lemma": self.lemma,
            "pos": self.pos,
            "level": self.level,
            "group": self.group,
            **({"hardGroup": self.hard_group} if self.hard_group and self.hard_group != self.group else {}),
            **({"domain": self.domain} if self.domain else {}),
            "definitions": [d.to_json() for d in sorted(self.definitions, key=lambda d: -d.quality)],
            **({"example": self.example} if self.example else {}),
            **({"exampleRu": self.example_ru} if self.example_ru else {}),
            **({"translation": self.translation} if self.translation else {}),
            **({"synonyms": self.see_also} if self.see_also else {}),
        }


@dataclass
class Question:
    id: str
    trainer: str
    entry_id: str
    lang: str
    distractors: list[str]
    status: Literal["ok", "needs_review"]
    reasons: list[str] = field(default_factory=list)
    hard: list[str] = field(default_factory=list)  # same-group distractors (hard mode), ≥ 2 or empty
    span: list[int] | None = None  # gap-fill: [start, end) of the word in the entry's example
    forms: list[str] = field(default_factory=list)  # gap-fill: word forms of [entry, *distractors]

    def to_json(self) -> dict:
        data = {
            "id": self.id,
            "trainer": self.trainer,
            "entryId": self.entry_id,
            "lang": self.lang,
            "distractors": self.distractors,
            "status": self.status,
        }
        if self.hard:
            data["hard"] = self.hard
        if self.span:
            data["span"] = self.span
            data["forms"] = self.forms
        if self.reasons:
            data["reasons"] = self.reasons
        return data


def stable_order(items: list, salt: str) -> list:
    """A fixed pseudo-random order of entries for one question: each item's place depends only
    on (salt, its id), so adding or removing other words does not reshuffle the rest (and the
    gap-fill model cache keeps matching the candidates it already judged)."""
    import zlib

    return sorted(items, key=lambda e: (zlib.crc32(f"{salt}|{e.id}".encode()), e.id))

