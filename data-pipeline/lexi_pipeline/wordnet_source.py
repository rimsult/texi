"""WordNet (via NLTK) adapter: definitions, examples, semantic groups, sense keys."""
from __future__ import annotations

from functools import lru_cache

from .gapfill import _pattern, word_forms
from .models import POS_TO_WN, QUALITY, Definition, Entry
from .text import clean_gloss, leaks


def _load_wordnet():
    from nltk.corpus import wordnet as wn

    wn.ensure_loaded()
    return wn



def _ordered(related: list) -> list:
    """NLTK lists related synsets/lemmas in hash order, which changes between runs."""
    return sorted(related, key=repr)  # Synset('free.a.02'), Lemma('free.a.02.free')

class WordNetSource:
    def __init__(self, wn=None, max_senses: int = 5):
        self.wn = wn or _load_wordnet()
        self.max_senses = max_senses

    def synsets(self, variants: list[str], pos: str):
        wn_pos = POS_TO_WN[pos]
        for v in variants:
            key = v.replace(" ", "_")
            found = self.wn.synsets(key, wn_pos)
            keys = {key.lower(), (self.wn.morphy(key, wn_pos) or key).lower()}
            matching = [s for s in found if keys & {l.name().lower() for l in s.lemmas()}]
            if matching:
                return matching
        return []

    def synset(self, name: str):
        return self.wn.synset(name)

    def group_of(self, synset) -> str:
        """Semantic group: lexicographer file for nouns/verbs, adjective cluster head
        for adjectives, and the pertainym's group (or the synset) for adverbs."""
        pos = synset.pos()
        if pos in ("n", "v"):
            return synset.lexname()
        if pos == "s":
            heads = _ordered(synset.similar_tos())
            return "adj:" + (heads[0].name() if heads else synset.name())
        if pos == "a":
            if synset.lexname() == "adj.pert":
                for lemma in synset.lemmas():
                    for p in _ordered(lemma.pertainyms()):
                        return "pert:" + p.synset().lexname()
            return "adj:" + synset.name()
        if pos == "r":
            for lemma in synset.lemmas():
                for p in _ordered(lemma.pertainyms()):
                    return self.group_of(p.synset())
            return "adv:" + synset.name()
        return synset.lexname()

    def first_gloss(self, word: str, pos: str) -> tuple[str, object] | None:
        syns = self.synsets([word], pos)
        for s in syns[:2]:
            gloss = clean_gloss(s.definition())
            if gloss:
                return gloss, s
        return None

    def enrich(self, entry: Entry) -> bool:
        syns = self.synsets(entry.variants or [entry.lemma], entry.pos)
        if not syns:
            return False
        entry.senses = {s.name() for s in syns}
        entry.top_senses = [s.name() for s in syns[:6]]
        chosen = None
        heads = [entry.lemma] + entry.variants
        for rank, s in enumerate(syns[: self.max_senses]):
            if s.instance_hypernyms():
                continue  # a named entity ("Singer": the inventor), not the word's meaning
            gloss = clean_gloss(s.definition())
            if not gloss or leaks(gloss, heads):
                continue
            entry.definitions.append(
                Definition(gloss, "en", "wordnet", round(QUALITY["wordnet"] - 0.05 * rank, 2))
            )
            chosen = s
            break
        chosen = chosen or syns[0]
        self.apply_synset(entry, chosen)
        return True

    def apply_synset(self, entry: Entry, chosen) -> None:
        """Semantic metadata of the sense that the entry's definition describes."""
        entry.synset = chosen.name()
        entry.group = self.group_of(chosen)
        entry.hard_group = self.hard_group_of(chosen)
        entry.ancestors = set(self.ancestor_depths(chosen.name())) - {chosen.name()}
        entry.synonyms = {l.name().replace("_", " ").lower() for l in chosen.lemmas()}
        # Only examples that use the word itself: WordNet often illustrates a sense with a
        # synonym ("The apartment was immaculate." for "spotless"), which confuses learners.
        uses_word = _pattern({f for head in [entry.lemma, *entry.variants] for f in word_forms(head, entry.pos)}
                             or {entry.lemma.lower()})
        for ex in chosen.examples():
            if 3 <= len(ex.split()) <= 18 and uses_word.search(ex):
                entry.example = ex[0].upper() + ex[1:] + ("" if ex.endswith((".", "!", "?")) else ".")
                break

    def hard_group_of(self, synset) -> str:
        """Group used by hard mode. Nouns/verbs: lexicographer file. Descriptive adjectives:
        the antonym family of their cluster (big ↔ small), so distractors are related but
        never near-synonyms from the same cluster. Adverbs follow their adjective."""
        pos = synset.pos()
        if pos in ("n", "v"):
            return synset.lexname()
        if pos in ("a", "s"):
            if synset.lexname() == "adj.pert":
                return self.group_of(synset)
            heads = _ordered(synset.similar_tos()) if pos == "s" else [synset]
            head = heads[0] if heads else synset
            family = {head.name()} | {a.synset().name() for l in head.lemmas() for a in l.antonyms()}
            return "adjfam:" + min(family)
        if pos == "r":
            for lemma in synset.lemmas():
                for p in _ordered(lemma.pertainyms()):
                    return self.hard_group_of(p.synset())
            return "adv:" + synset.name()
        return synset.lexname()

    @lru_cache(maxsize=200_000)
    def ancestor_depths(self, name: str) -> dict[str, int]:
        """Synset + all (instance) hypernyms -> max depth. Cached; used for fast similarity."""
        s = self.synset(name)
        out = {name: s.max_depth()}
        for a in s.closure(lambda x: x.hypernyms() + x.instance_hypernyms()):
            out[a.name()] = a.max_depth()
        return out

    def fast_similarity(self, a: str, b: str) -> float:
        """Wu–Palmer-style score from cached ancestor depths (≈100x faster than NLTK's,
        same ordering in practice). 0 when there is no common ancestor."""
        da, db = self.ancestor_depths(a), self.ancestor_depths(b)
        common = da.keys() & db.keys() if len(da) < len(db) else db.keys() & da.keys()
        if not common:
            return 0.0
        lcs = max(da[c] for c in common)
        return 2 * (lcs + 1) / (da[a] + 1 + db[b] + 1)

    @lru_cache(maxsize=500_000)
    def similarity(self, a: str, b: str) -> float:
        sa, sb = self.synset(a), self.synset(b)
        if sa.pos() != sb.pos() or sa.pos() not in ("n", "v"):
            return 0.0
        return sa.wup_similarity(sb) or 0.0
