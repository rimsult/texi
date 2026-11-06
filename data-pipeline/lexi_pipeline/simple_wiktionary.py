"""Simple English Wiktionary (kaikki.org / wiktextract extract): learner definitions.

Its entries are written for learners in basic English, Cobuild-style ("If you run, you
go quickly…", "A bicycle is a vehicle with two wheels…"), with simple examples. Licence:
CC BY-SA (Wiktionary). The pipeline turns a gloss into an option text that never shows
the headword: "A bicycle is X" → "X"; frames that use the word ("If you run, you…") are
rewritten into dictionary form (rewrite.py).
"""
from __future__ import annotations

import gzip
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .rewrite import BLANK, rewrite
from .text import stem, tokens

POS_MAP = {"noun": "noun", "verb": "verb", "adj": "adjective", "adv": "adverb"}
# Senses a learner should not meet in a vocabulary trainer.
SKIP_TAGS = {"slang", "vulgar", "offensive", "derogatory", "old, no longer used", "rare", "Internet slang",
             "obsolete", "archaic", "dated", "euphemism", "humorous", "childish", "proscribed"}
SOFT_TAGS = {"informal", "figurative", "by extension", "idiomatic", "US", "UK", "Australia", "Canada", "British"}
_BAD_START = re.compile(
    r"^(the )?(alternative|plural|past|present|third[- ]person|comparative|superlative|short for|another (word|way)|"
    r"see\b|same as|a form of|misspelling|abbreviation|initialism|acronym|contraction|"
    r"(the )?(simple )?past tense|(the )?past participle)", re.I)
_PROPER = {"english", "god", "christmas", "british", "american", "europe", "european", "america", "england",
           "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "january", "february",
           "march", "april", "june", "july", "august", "september", "october", "november", "december",
           "christian", "christians", "jewish", "muslim", "earth", "internet", "latin", "greek", "french"}
STOP = {
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "at", "for", "with", "by", "from", "as", "is",
    "are", "was", "were", "be", "been", "being", "it", "its", "that", "this", "these", "those", "which",
    "who", "whom", "what", "when", "where", "how", "if", "you", "your", "someone", "something", "somebody",
    "people", "person", "thing", "things", "one", "ones", "has", "have", "had", "do", "does", "did", "can",
    "could", "will", "would", "may", "might", "must", "should", "not", "no", "very", "more", "most", "some",
    "any", "all", "other", "such", "than", "then", "so", "into", "out", "up", "about", "used", "use",
    "using", "make", "makes", "made", "they", "them", "their", "he", "she", "him", "her", "his", "we", "us",
    "our", "i", "me", "my", "there", "usually", "often", "also", "way", "kind", "type", "part", "act",
}


# Words that carry no meaning of their own (a definition needs at least one other word).
_FUNCTION = {"a", "an", "the", "and", "or", "of", "to", "in", "on", "at", "for", "with", "by", "from", "as",
             "is", "are", "was", "were", "be", "been", "being", "it", "its", "that", "this", "which", "who",
             "what", "when", "where", "if", "you", "your", "someone", "something", "somebody", "people",
             "person", "thing", "things", "one", "has", "have", "do", "does", "not", "very", "so", "they",
             "them", "their", "he", "she", "him", "her", "his", "there"}


@dataclass
class SimpleSense:
    index: int
    gloss: str
    examples: list[str] = field(default_factory=list)
    synonyms: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    @property
    def skipped(self) -> bool:
        return bool(SKIP_TAGS & set(self.tags))


@dataclass
class SimpleEntry:
    word: str
    pos: str
    senses: list[SimpleSense]
    forms: set[str] = field(default_factory=set)


class SimpleWiktionary:
    """(word, pos) → senses. ``wanted`` limits memory to the words the pipeline needs."""

    def __init__(self, entries: dict[tuple[str, str], SimpleEntry] | None = None):
        self.entries = entries or {}

    @classmethod
    def load(cls, path: Path, wanted: set[str] | None = None) -> "SimpleWiktionary":
        out: dict[tuple[str, str], SimpleEntry] = {}
        opener = gzip.open if str(path).endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                raw = json.loads(line)
                pos = POS_MAP.get(raw.get("pos", ""))
                word = raw.get("word", "")
                if not pos or not word or (wanted is not None and word.lower() not in wanted):
                    continue
                senses = []
                for s in raw.get("senses", []):
                    gloss = (s.get("glosses") or [""])[0].strip()
                    if not gloss:
                        continue
                    senses.append(SimpleSense(
                        index=len(senses), gloss=gloss,
                        examples=[x["text"].strip() for x in s.get("examples", []) if x.get("text")],
                        synonyms=[x["word"] for x in s.get("synonyms", []) if x.get("word")],
                        tags=[*s.get("raw_tags", []), *s.get("tags", [])]))
                key = (word.lower(), pos)
                forms = {f["form"].lower() for f in raw.get("forms", []) if f.get("form") and " " not in f["form"]}
                if key in out:  # several etymologies: keep one sense order
                    prev = out[key]
                    for s in senses:
                        s.index = len(prev.senses)
                        prev.senses.append(s)
                    prev.forms |= forms
                else:
                    out[key] = SimpleEntry(word, pos, senses, forms)
        return cls(out)

    def get(self, word: str, pos: str) -> SimpleEntry | None:
        return self.entries.get((word.lower(), pos))

    def __len__(self) -> int:
        return len(self.entries)


def head_forms(word: str, extra: set[str] | None = None) -> set[str]:
    """Inflections that must be masked: run → runs, ran (from the entry), running…"""
    w = word.lower()
    forms = {w, w + "s", w + "es", w + "ed", w + "d", w + "ing", w + "'s", w + "er", w + "est"}
    if w.endswith("e"):
        forms |= {w[:-1] + "ing", w[:-1] + "ed"}
    if w.endswith("y"):
        forms |= {w[:-1] + "ies", w[:-1] + "ied", w[:-1] + "ier", w[:-1] + "iest"}
    if re.search(r"(^|[^aeiou])[aeiou][bdgklmnprt]$", w):
        forms |= {w + w[-1] + "ing", w + w[-1] + "ed", w + w[-1] + "er", w + w[-1] + "est"}
    return forms | {f.lower() for f in (extra or set()) if f}


def _form_pattern(forms: set[str]) -> str:
    return "|".join(re.escape(f) for f in sorted(forms, key=len, reverse=True))


def _lower_first(text: str) -> str:
    first = text.split(" ", 1)[0]
    if first and first[0].isupper() and (len(first) == 1 and first != "I" or first[1:].islower()) \
            and first.lower().strip(",'") not in _PROPER:
        return text[0].lower() + text[1:]
    return text


def learner_definition(gloss: str, word: str, forms: set[str] | None = None, max_words: int = 26,
                       pos: str | None = None) -> str | None:
    """Option text from a Simple Wiktionary gloss, without the headword.

    "A bicycle is a vehicle with two wheels. You use your legs to make it move."
        → "a vehicle with two wheels; you use your legs to make it move"
    "If you carry something, you lift it up…" → "to lift something up…" (see rewrite.py)

    A clause that cannot do without the word is dropped; when that is the main one, there is
    no learner definition (None) and the entry keeps its WordNet gloss.
    """
    text = re.sub(r"\([^()]*\)", "", gloss)
    text = re.sub(r"\s+", " ", re.sub(r'["“”]', "", text)).strip()  # quotes around the headword
    if not text or _BAD_START.match(text):
        return None
    pat = _form_pattern(head_forms(word, forms))
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text) if s.strip()]
    # "In grammar, a sentence is …": the field label goes, the definition stays
    first = re.sub(rf"^In [a-z]+(?: [a-z]+)?, (?=(?:(?:an?|the|your|some)\s+)?(?:{pat})\s+(?:is|are|means)\b)", "",
                   sentences[0], flags=re.I)
    m = re.match(rf"^(?:(?:an?|the|your|some)\s+)?(?:{pat})\s+(?:is|are)\s+"
                 rf"(?!when\b|where\b|if\b|what\b|how\b|why\b|because\b)(.+)$", first, re.I)
    if not m:
        m = re.match(rf"^(?:the\s+word\s+)?(?:{pat})\s+means\s+(.+)$", first, re.I)
    if m:
        first = m.group(1)
        if _BAD_START.match(first):
            return None  # "Am is another way of spelling a.m."
    parts, n = [], 0
    for i, s in enumerate([first, *sentences[1:]]):
        s = s.strip().rstrip(".!;: ").strip()
        w = len(s.split())
        if i and n + w > max_words:
            break
        parts.append(_lower_first(s))
        n += w
    parts = [c.strip() for p in parts for c in p.split("; ") if c.strip()]  # "…meter; 100 ___ is one meter"
    kept: list[str] = []
    rewritten = False
    for i, part in enumerate(parts):
        masked = re.sub(rf"(?<![\w-])(?:{pat})(?![\w-])", BLANK, part, flags=re.I)
        masked = re.sub(r"\s+([,;.])", r"\1", masked).strip(" ,;")
        if BLANK in masked:
            masked = rewrite(masked, pos)
            rewritten = rewritten or (masked is not None and i == 0)
            if masked is None:
                if i == 0:
                    return None  # the definition itself needs the word
                continue  # "…; 100 ___ is one meter": an aside, dropped
        kept.append(masked)
    text = "; ".join(kept)
    words = text.split()
    content = [t for t in tokens(text) if t not in _FUNCTION]
    if len(words) > max_words + 4 or not content:
        return None
    if len(words) < 3 and len(content) < 2 and not (rewritten and len(words) == 2):
        return None  # "Lucky."; "great fear" and a rewritten "not good" are fine
    return text


def learner_example(sense: SimpleSense, word: str, forms: set[str] | None = None) -> str | None:
    """A short example sentence that actually uses the word (the shortest of the good ones)."""
    pat = _form_pattern(head_forms(word, forms))
    good = []
    for ex in sense.examples:
        ex = re.sub(r"\s+", " ", ex).strip().strip('"“”')
        n = len(ex.split())
        if 3 <= n <= 18 and ex[0].isupper() and re.search(rf"(?<![\w-])(?:{pat})(?![\w-])", ex, re.I):
            good.append(ex if ex.endswith((".", "!", "?")) else ex + ".")
    return min(good, key=lambda x: len(x.split())) if good else None


def content_stems(text: str) -> set[str]:
    return {stem(t)[:6] for t in tokens(text) if t not in STOP and len(t) > 2}


def match_sense(entry: SimpleEntry, anchor: set[str], max_index: int = 4) -> tuple[SimpleSense, float] | None:
    """Simple sense describing the same meaning as the WordNet sense (``anchor`` = content
    stems of its gloss, synonyms, examples and hypernyms). Earlier senses are preferred."""
    best: tuple[SimpleSense, float] | None = None
    own_word = content_stems(entry.word)
    for s in entry.senses:
        if s.skipped or s.index > max_index:
            continue
        own = content_stems(" ".join([s.gloss, *s.examples[:2], *s.synonyms[:6]])) - own_word
        score = len(own & anchor) + (0.75 if s.index == 0 else 0.35 if s.index == 1 else 0.0)
        score -= 0.5 * bool(SOFT_TAGS & set(s.tags))
        if best is None or score > best[1]:
            best = (s, score)
    return best
