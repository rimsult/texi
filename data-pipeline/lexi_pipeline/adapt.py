"""Level-adaptive definitions.

Every word gets the definition that suits *its* level: A1–B1 words prefer Simple English
Wiktionary (learner definitions in basic words), C1–C2 words keep the precise WordNet
gloss, B2 takes whichever is easier. "Easier" is measured, not guessed: the share of
content words in the definition that are above the learner's level + 1 (CEFR lists,
frequency-estimated for words outside them), weighted by how far above.
"""
from __future__ import annotations

from collections import Counter
from typing import Callable, Iterable

from .models import LEVELS, QUALITY, Definition, Entry, level_index
from .simple_wiktionary import (BLANK, SOFT_TAGS, STOP, SimpleWiktionary, content_stems, learner_definition,
                                learner_example)
from .technical import estimate_level
from .text import clean_gloss, leaks, stem, tokens

WEAK_ZIPF = 5.4  # "time", "place", "together": too common to show which meaning is meant
TECH_TAGS = {"computing", "mathematics", "physics", "chemistry", "technical", "science", "engineering",
             "geometry", "electricity", "electronics", "statistics", "astronomy", "biology", "internet"}


class Vocabulary:
    """Word → CEFR level index (lists first, then a frequency estimate)."""

    def __init__(self, levels: dict[str, int], zipf: Callable[[str], float], thresholds: list[float], wn=None):
        self.levels = levels
        self.zipf = zipf
        self.thresholds = thresholds
        self.wn = wn
        self._cache: dict[str, int] = {}

    @classmethod
    def from_entries(cls, entries: Iterable[Entry], zipf, thresholds, wn=None) -> "Vocabulary":
        levels: dict[str, int] = {}
        for e in entries:
            if e.level_source != "cefr":
                continue
            for w in [e.lemma, *e.variants]:
                w = w.lower()
                levels[w] = min(levels.get(w, 9), level_index(e.level))
        return cls(levels, zipf, thresholds, wn)

    def level_of(self, word: str) -> int:
        w = word.lower()
        if w in self._cache:
            return self._cache[w]
        lvl = self.levels.get(w)
        if lvl is None and self.wn is not None:
            for pos in ("n", "v", "a", "r"):
                base = self.wn.morphy(w, pos)
                if base and base in self.levels:
                    lvl = self.levels[base] if lvl is None else min(lvl, self.levels[base])
        if lvl is None:
            lvl = level_index(estimate_level(self.zipf(w), self.thresholds, floor=LEVELS[0]))
        self._cache[w] = lvl
        return lvl

    def difficulty(self, text: str, ceiling: int) -> float:
        """Share of content words above ``ceiling`` (0 = every word is known at that level)."""
        words = [t for t in tokens(text.replace(BLANK, " ")) if t not in STOP and len(t) > 2]
        if not words:
            return 0.0
        return sum(self.level_of(t) > ceiling for t in words) / len(words)


def synset_anchor(wnsrc, name: str, extra: Iterable[str] = ()) -> set[str]:
    """Content stems describing a WordNet sense (gloss, examples, lemmas, hypernyms)."""
    s = wnsrc.synset(name)
    parts = [s.definition(), *s.examples(), *extra]
    parts += [l.name().replace("_", " ") for l in s.lemmas()]
    for h in sorted(s.hypernyms())[:3]:  # NLTK's order varies between runs
        parts += [l.name().replace("_", " ") for l in h.lemmas()[:3]]
    return content_stems(" ".join(parts))


def cost(vocab: "Vocabulary", text: str, ceiling: int) -> float:
    """How hard a definition is for a learner at ``ceiling``: levels above it, summed over
    the content words (dusk at A1 costs 3, sunset 1), plus a little for every word past 14."""
    words = [t for t in tokens(text.replace(BLANK, " ")) if t not in STOP and len(t) > 2]
    return sum(max(0, vocab.level_of(t) - ceiling) for t in words) + 0.25 * max(0, len(text.split()) - 14)


def prefers_simple(level: str, c_simple: float, c_wordnet: float | None) -> bool:
    if c_wordnet is None:
        return True
    i = level_index(level)
    if i <= 2:   # A1–B1: the learner definition unless it is clearly harder
        return c_simple <= c_wordnet + 2
    if i == 3:   # B2: whichever is easier
        return c_simple < c_wordnet
    return c_simple + 3 <= c_wordnet  # C1–C2: the precise gloss unless it is far harder


def _sense_count(wnsrc, name: str, lemma: str) -> int:
    """SemCor frequency of ``lemma`` in this sense (0 when untagged)."""
    key = lemma.lower().replace(" ", "_")
    return sum(l.count() for l in wnsrc.synset(name).lemmas() if l.name().lower() == key)


def _wordnet_gloss(wnsrc, name: str, heads: list[str]) -> str | None:
    gloss = clean_gloss(wnsrc.synset(name).definition())
    return gloss if gloss and not leaks(gloss, heads) else None


def adapt_definitions(entries: list[Entry], simple: SimpleWiktionary, wnsrc, vocab: Vocabulary,
                      stats: Counter, log: list | None = None,
                      repick: Callable[[Entry], bool] = lambda e: e.deck == "general") -> None:
    """Give each entry the definition that suits its level.

    The Simple Wiktionary sense must describe the same meaning as a WordNet sense (content
    overlap, or both dictionaries' *main* sense). For the general deck any of the word's
    frequent WordNet senses may match — the entry then switches to that sense, so groups,
    synonyms and distractor checks follow the meaning that is shown ("stop" = a bus stop,
    not "the event of something ending"). Technical entries keep their pinned sense.
    ``log`` (optional) collects one record per decision, for editors (out/adapt_log.json)."""
    anchors: dict[str, set[str]] = {}

    def note(e: Entry, reason: str, **kw) -> None:
        if log is not None:
            log.append({"id": e.id, "level": e.level, "reason": reason, **kw})

    for e in entries:
        se = next((x for v in [e.lemma, *e.variants] if (x := simple.get(v, e.pos))), None)
        if se is None:
            continue
        stats["simple_found"] += 1
        heads = [e.lemma, *e.variants]
        usable = []
        for s in se.senses:
            if s.skipped or s.index > 3:
                continue
            text = learner_definition(s.gloss, se.word, se.forms, pos=se.pos)
            if text and not leaks(text, heads):
                usable.append((s, text))
        if not usable:
            stats["simple_unusable"] += 1
            note(e, "unusable", gloss=se.senses[0].gloss if se.senses else None)
            continue
        general = repick(e)
        if e.synset:
            names = [n for n in (e.top_senses if general else []) if not wnsrc.synset(n).instance_hypernyms()]
            names = [e.synset] + [n for n in names if n != e.synset]
        else:
            names = []
        if general:
            # A general word is explained by its *main* learner sense ("watch" = the clock on your
            # arm, not a ship's duty period). When that one is unusable, a later sense may stand
            # in only for the entry's own WordNet sense ("driver" ≠ a golf club).
            plain = [u for u in usable if not SOFT_TAGS & set(u[0].tags)] or usable
            usable = plain[:1]
            if usable[0][0].index > 0:
                names = names[:1]
        own_word = content_stems(se.word)
        evidence: dict[str, int] = {}
        best = None  # (score, sense, text, synset name or None)
        for s, text in usable:
            learner = " ".join([s.gloss, *s.examples[:2], *s.synonyms[:6]])
            own = content_stems(learner) - own_word
            # very common words ("time", "together") are weak evidence for a change of meaning
            weak = {stem(t)[:6] for t in tokens(learner) if vocab.zipf(t) >= WEAK_ZIPF}
            soft = 0.5 * bool(SOFT_TAGS & set(s.tags))
            prior_s = 0.75 if s.index == 0 else 0.35 if s.index == 1 else 0.0
            if not names:  # no WordNet sense to compare with: the main learner sense
                if s.index == 0:
                    best = (prior_s, s, text, None)
                continue
            for rank, name in enumerate(names):
                if name not in anchors:
                    anchors[name] = synset_anchor(wnsrc, name) - own_word
                anchor = anchors[name] | (anchor_extra(e) - own_word if name == e.synset else set())
                overlap = len(own & anchor)
                evidence[name] = len((own & anchor) - weak)
                wn_rank = e.top_senses.index(name) if name in e.top_senses else 9
                if e.deck == "tech":
                    # Technical senses are rarely a word's everyday meaning ("address" = a memory
                    # location): real overlap is required, and more of it without a field label.
                    if overlap < (1 if TECH_TAGS & set(s.tags) else 2):
                        continue
                elif overlap < 1 and not (s.index == 0 and wn_rank == 0):
                    continue
                score = overlap + prior_s + (0.5 if wn_rank == 0 else 0.25 if wn_rank == 1 else 0.0) - soft \
                    + (0.3 if name == e.synset else 0.0) + (1.0 if e.deck == "tech" and TECH_TAGS & set(s.tags) else 0.0)
                if best is None or score > best[0]:
                    best = (score, s, text, name)
        if best is None:
            stats["simple_sense_unmatched"] += 1
            note(e, "unmatched", gloss=usable[0][0].gloss, wordnet=getattr(e.best_definition("en"), "text", None))
            continue
        _, sense, text, name = best
        if general and name and e.synset and name != e.synset:
            # Switching meaning needs more evidence than staying, more still when the new sense is
            # rarer in SemCor ("rent" ≠ a rip), and never to a marginal sense ("group" of atoms).
            n_new, n_cur = _sense_count(wnsrc, name, e.lemma), _sense_count(wnsrc, e.synset, e.lemma)
            marginal = (n_cur >= 20 and n_new * 20 < n_cur) or (n_cur >= 5 and n_new == 0)
            gain = evidence.get(name, 0) - evidence.get(e.synset, 0)
            if marginal and gain >= 2:
                # the learner dictionary clearly describes a marginal meaning ("brand" = a burning
                # piece of wood): keep the dictionary definition of the main one
                stats["simple_marginal_sense"] += 1
                note(e, "marginal", gloss=sense.gloss, wordnet=getattr(e.best_definition("en"), "text", None))
                continue
            if marginal or gain < 1 + (n_new * 2 < n_cur):
                name = e.synset
        ceiling = min(len(LEVELS) - 1, level_index(e.level) + 1)
        if name and name != e.synset:
            wn_text = _wordnet_gloss(wnsrc, name, heads)
        else:
            wn_def = e.best_definition("en")
            wn_text = wn_def.text if wn_def and wn_def.source in ("wordnet", "wiktionary") else None
        c_simple, c_wn = cost(vocab, text, ceiling), (cost(vocab, wn_text, ceiling) if wn_text else None)
        example = learner_example(sense, se.word, se.forms)
        if not prefers_simple(e.level, c_simple, c_wn):
            stats["simple_not_easier"] += 1
            note(e, "not_easier", text=text, wordnet=wn_text, cost_simple=round(c_simple, 2),
                 cost_wordnet=round(c_wn or 0, 2))
            if example and not e.example and level_index(e.level) <= 3 and (not name or name == e.synset):
                e.example = example
            continue
        if name and name != e.synset:  # follow the meaning that is shown
            e.example = None  # the old sense's example would not fit
            wnsrc.apply_synset(e, wnsrc.synset(name))
            e.definitions = [d for d in e.definitions if d.source not in ("wordnet", "generated")]
            if wn_text:
                e.definitions.append(Definition(wn_text, "en", "wordnet", QUALITY["wordnet"]))
            e.sense_changed = True
            stats["simple_sense_switched"] += 1
        e.definitions.append(Definition(text, "en", "simple", QUALITY["simple"]))
        e.mt_source = text  # already without the headword
        if example and (level_index(e.level) <= 2 or not e.example):
            e.example = example
        stats["simple_used"] += 1
        stats[f"simple_used:{e.level}"] += 1
        note(e, "used", text=text, wordnet=wn_text, cost_simple=round(c_simple, 2),
             cost_wordnet=round(c_wn, 2) if c_wn is not None else None)


def anchor_for(entry: Entry, wnsrc) -> set[str]:
    """Content stems of the entry's own sense (its synset + its current definitions)."""
    out = anchor_extra(entry)
    if entry.synset:
        out |= synset_anchor(wnsrc, entry.synset)
    return out - content_stems(entry.lemma)


def anchor_extra(entry: Entry) -> set[str]:
    return content_stems(" ".join([*(d.text for d in entry.definitions if d.lang == "en"), *sorted(entry.synonyms)]))


def readability_report(entries: Iterable[Entry], vocab: Vocabulary) -> dict[str, float]:
    """Mean share of above-level words in the shipped English definitions, per level."""
    acc: dict[str, list[float]] = {l: [] for l in LEVELS}
    for e in entries:
        d = e.best_definition("en")
        if d:
            acc[e.level].append(vocab.difficulty(d.text, min(len(LEVELS) - 1, level_index(e.level) + 1)))
    return {l: round(sum(v) / len(v), 3) for l, v in acc.items() if v}
