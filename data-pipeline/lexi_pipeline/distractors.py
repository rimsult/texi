"""Distractor selection rules.

A distractor must (a) share the target's part of speech, (b) be within ±1 CEFR
level, (c) come from a *different* semantic group, and must never be a synonym,
share a sense or a translation with the target. Questions without at least two
valid distractors are marked ``needs_review`` and never shipped to users.

Hard mode (optional, per question) flips rule (c): distractors come from the *same*
semantic group and are ranked by similarity, so the learner has to tell close
concepts apart (lunch / dinner / breakfast). To keep exactly one correct answer it
adds stricter checks: no hypernym/hyponym pairs (dog / animal), no near-synonyms
(same adjective cluster, any shared translation across all senses), no option that
is too close to *any* sense of the other word, and both leak directions.

Profanity, sexual and insulting words (``text.SENSITIVE``) are taught as answers but are
never used as distractors.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Callable, Iterable

from .models import LEVELS, Entry, Question, allowed_langs, level_index, stable_order
from .text import leaks, ru_mentions, sensitive

TRAINERS = ("word-to-definition", "definition-to-word")
MIN_DISTRACTORS = 2
POOL_SIZE = 5
SIMILARITY_LIMIT = 0.8
HARD_SIMILARITY_LIMIT = 0.93
HARD_SIMILARITY_LIMIT_VERB = 0.83  # verb trees are shallow: siblings score higher (blame / scold)
HARD_SCAN = 400  # candidates examined per target in hard mode (most similar first)

Similarity = Callable[[Entry, Entry], float]


def translation_clash(target: Entry, cand: Entry, tdef: str, cdef: str) -> bool:
    """Russian definitions are translations, so the leak check works on Russian words:
    "puppy" = «молодая собака» must not be an option for "dog" (and vice versa)."""
    return ru_mentions(cdef, target.ru_terms) or ru_mentions(tdef, cand.ru_terms)


def rejection_reason(target: Entry, cand: Entry, trainer: str, lang: str,
                     similarity: Similarity | None = None) -> str | None:
    if cand.id == target.id or cand.lemma.lower() == target.lemma.lower():
        return "same_word"
    if cand.pos != target.pos:
        return "pos_mismatch"
    if sensitive(cand.lemma, cand.pos):
        return "sensitive_word"
    if abs(level_index(cand.level) - level_index(target.level)) > 1:
        return "level_out_of_range"
    if not target.group or not cand.group:
        return "unknown_semantic_group"
    if cand.group == target.group:
        return "same_semantic_group"
    if cand.senses & target.senses:
        return "shared_sense"
    if cand.lemma.lower() in target.synonyms or target.lemma.lower() in cand.synonyms:
        return "synonym"
    if cand.ru_terms & target.ru_terms:
        return "shared_translation"
    target_def = target.best_definition(lang)
    if target_def is None:
        return "target_without_definition"
    # Both trainers: the client re-checks every option against its definition, and two
    # words with the same gloss would both be right in definition → word.
    cdef = cand.best_definition(lang)
    if cdef is None:
        return "no_definition_in_lang"
    if cdef.text.strip().lower() == target_def.text.strip().lower():
        return "duplicate_definition"
    if lang == "ru" and translation_clash(target, cand, target_def.text, cdef.text):
        return "ru_definition_mentions_translation"
    if trainer == "word-to-definition":
        if leaks(cdef.text, [target.lemma, *target.variants]):
            return "definition_mentions_target"
    elif trainer == "definition-to-word":
        if leaks(target_def.text, [cand.lemma]):
            return "candidate_in_definition"
    else:
        raise ValueError(f"unknown trainer {trainer}")
    if similarity and similarity(target, cand) >= SIMILARITY_LIMIT:
        return "too_similar"
    return None


def hard_rejection_reason(target: Entry, cand: Entry, lang: str,
                          similarity: Similarity | None = None) -> str | None:
    """Rules for hard-mode distractors; a candidate must pass for both trainers."""
    if cand.id == target.id or cand.lemma.lower() == target.lemma.lower():
        return "same_word"
    if cand.pos != target.pos:
        return "pos_mismatch"
    if sensitive(cand.lemma, cand.pos):
        return "sensitive_word"
    if abs(level_index(cand.level) - level_index(target.level)) > 1:
        return "level_out_of_range"
    if not target.hard_group or not cand.hard_group:
        return "unknown_semantic_group"
    if cand.hard_group != target.hard_group:
        return "different_semantic_group"
    if target.group and target.group.startswith("adj:") and cand.group == target.group:
        return "same_cluster"  # satellites of one adjective cluster are near-synonyms
    if cand.senses & target.senses:
        return "shared_sense"
    if cand.lemma.lower() in target.synonyms or target.lemma.lower() in cand.synonyms:
        return "synonym"
    if (cand.ru_terms | cand.ru_all) & (target.ru_terms | target.ru_all):
        return "shared_translation"
    if (cand.synset and cand.synset in target.ancestors) or (target.synset and target.synset in cand.ancestors) \
            or cand.senses & target.ancestors or target.senses & cand.ancestors:
        return "hypernym_relation"
    tdef, cdef = target.best_definition(lang), cand.best_definition(lang)
    if tdef is None:
        return "target_without_definition"
    if cdef is None:
        return "no_definition_in_lang"
    if cdef.text.strip().lower() == tdef.text.strip().lower():
        return "duplicate_definition"
    if lang == "ru" and translation_clash(target, cand, tdef.text, cdef.text):
        return "ru_definition_mentions_translation"
    if leaks(cdef.text, [target.lemma, *target.variants]):
        return "definition_mentions_target"
    if leaks(tdef.text, [cand.lemma, *cand.variants]):
        return "candidate_in_definition"
    limit = HARD_SIMILARITY_LIMIT_VERB if target.pos == "verb" else HARD_SIMILARITY_LIMIT
    if similarity and similarity(target, cand) >= limit:
        return "too_similar"
    return None


def same_option(cand: Entry, chosen: list[Entry], lang: str) -> bool:
    """Same synset or identical gloss as an option already picked."""
    cdef = cand.best_definition(lang)
    ctext = cdef.text.strip().lower() if cdef else ""
    return any((cand.synset and cand.synset == o.synset)
               or ((d := o.best_definition(lang)) is not None and d.text.strip().lower() == ctext)
               for o in chosen)


def clashes_with_chosen(cand: Entry, chosen: list[Entry], lang: str) -> bool:
    """Two options of one question must differ from each other too (decorate / adorn
    share a synset and the same gloss — showing both would be a giveaway)."""
    cdef = cand.best_definition(lang)
    ctext = cdef.text.strip().lower() if cdef else ""
    for o in chosen:
        if cand.senses & o.senses or (cand.synset and cand.synset == o.synset):
            return True
        odef = o.best_definition(lang)
        if odef and odef.text.strip().lower() == ctext:
            return True
        if (cand.ru_terms | cand.ru_all) & (o.ru_terms | o.ru_all):
            return True
    return False


class DistractorIndex:
    def __init__(self, entries: Iterable[Entry], similarity: Similarity | None = None,
                 hard_similarity: Similarity | None = None, rank: Similarity | None = None):
        self.by_pos_level: dict[tuple[str, str], list[Entry]] = defaultdict(list)
        self.by_hard_group: dict[tuple[str, str], list[Entry]] = defaultdict(list)
        for e in entries:
            self.by_pos_level[(e.pos, e.level)].append(e)
            if e.hard_group:
                self.by_hard_group[(e.pos, e.hard_group)].append(e)
        self.similarity = similarity
        self.hard_similarity = hard_similarity
        self.rank = rank

    def hard_pool(self, target: Entry, lang: str, size: int = POOL_SIZE) -> list[Entry]:
        """Same-group distractors, most similar first (deterministic)."""
        if not target.hard_group or target.best_definition(lang) is None:
            return []
        i = level_index(target.level)
        cands = [c for c in self.by_hard_group.get((target.pos, target.hard_group), [])
                 if abs(level_index(c.level) - i) <= 1 and c.id != target.id]
        cands = stable_order(cands, f"{target.id}|hard|{lang}")
        if self.rank:
            cands.sort(key=lambda c: -self.rank(target, c))
        valid: list[Entry] = []
        for c in cands[:HARD_SCAN]:
            if hard_rejection_reason(target, c, lang, self.hard_similarity) is None \
                    and not clashes_with_chosen(c, valid, lang):
                valid.append(c)
                if len(valid) >= size:
                    break
        return valid if len(valid) >= MIN_DISTRACTORS else []

    def candidates(self, target: Entry) -> list[Entry]:
        i = level_index(target.level)
        out: list[Entry] = []
        for lv in LEVELS[max(0, i - 1): i + 2]:
            out += self.by_pos_level.get((target.pos, lv), [])
        return out

    def pool(self, target: Entry, trainer: str, lang: str, size: int = POOL_SIZE,
             scan_valid: int = 24) -> list[Entry]:
        cands = stable_order(self.candidates(target), f"{target.id}|{trainer}|{lang}")
        valid: list[Entry] = []
        for c in cands:
            if rejection_reason(target, c, trainer, lang, self.similarity) is None \
                    and not same_option(c, valid, lang):
                valid.append(c)
                if len(valid) >= scan_valid:
                    break
        if trainer == "word-to-definition":
            tdef = target.best_definition(lang).text
            # Avoid giving the answer away by length: prefer options of similar length.
            valid.sort(key=lambda c: abs(len(c.best_definition(lang).text) - len(tdef)))
        return valid[:size]

    def build_question(self, target: Entry, trainer: str, lang: str) -> Question:
        qid = f"{target.id}:{trainer}:{lang}"
        reasons: list[str] = []
        if lang not in allowed_langs(target.level):
            reasons.append("lang_not_allowed_for_level")
        if target.best_definition(lang) is None:
            reasons.append("no_definition")
        if not target.group:
            reasons.append("unknown_semantic_group")
        if reasons:
            return Question(qid, trainer, target.id, lang, [], "needs_review", reasons)
        pool = self.pool(target, trainer, lang)
        if len(pool) < MIN_DISTRACTORS:
            return Question(qid, trainer, target.id, lang, [c.id for c in pool], "needs_review",
                            ["insufficient_distractors"])
        return Question(qid, trainer, target.id, lang, [c.id for c in pool], "ok")
