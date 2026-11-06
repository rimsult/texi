from __future__ import annotations

import re
import unicodedata

_STRESS = {"\u0301", "\u0300"}
_WORD = re.compile(r"[a-zA-Z]+(?:'[a-z]+)?")
_CYR = re.compile(r"^[а-яёА-ЯЁ\- ]+$")


def strip_stress(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    cleaned = "".join(ch for ch in decomposed if ch not in _STRESS)
    return unicodedata.normalize("NFC", cleaned)


def clean_gloss(gloss: str, max_words: int = 22) -> str | None:
    """Make a dictionary gloss learner-friendly: drop parentheticals, keep first clause."""
    text = re.sub(r"\([^()]*\)", "", gloss)
    text = text.split(";")[0]
    # WordNet often appends examples after a colon ("feline mammal …: domestic cats").
    head = re.split(r":\s", text, maxsplit=1)[0]
    if len(head.split()) >= 3:
        text = head
    text = re.sub(r"\s+", " ", text).strip(" ,.:")
    text = re.sub(r"\s+([,.])", r"\1", text)
    if not text:
        return None
    words = text.split()
    if len(words) <= max_words:
        return text
    # Too long for learners: cut at the last natural phrase boundary that fits.
    best = None
    for sep in (", ", " and ", " or ", " which ", " that ", " when "):
        start = 0
        while (i := text.find(sep, start)) != -1:
            head = text[:i].strip(" ,")
            n = len(head.split())
            if 5 <= n <= max_words and (best is None or n > len(best.split())):
                best = head
            start = i + 1
    return best


def tokens(text: str) -> list[str]:
    return [t.lower() for t in _WORD.findall(text)]


def _forms(word: str) -> set[str]:
    w = word.lower()
    forms = {w, w + "s", w + "es", w + "ed", w + "d", w + "ing", w + "er", w + "ers"}
    if w.endswith("e"):
        forms.add(w[:-1] + "ing")
    if w.endswith("y"):
        forms |= {w[:-1] + "ies", w[:-1] + "ied"}
    return forms


_SUFFIXES = ("ically", "ally", "ily", "ly", "ness", "ment", "ation", "ion", "ity", "ful", "less",
             "able", "ible", "ing", "ed", "er", "or", "est", "es", "s")


def stem(word: str) -> str:
    w = word.lower()
    for suf in _SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


def leaks(text: str, words: list[str] | set[str]) -> bool:
    """True if a headword, an inflection, or a word sharing its stem appears in the text.

    Prevents give-aways such as "quickly" -> "in a quick manner"."""
    toks = set(tokens(text))
    for word in words:
        parts = [p for p in re.split(r"[ _\-]", word.lower()) if p]
        if len(parts) > 1:
            if all(p in toks for p in parts if len(p) > 2):
                return True
            continue
        if not parts:
            continue
        if toks & _forms(parts[0]):
            return True
        st = stem(parts[0])
        if len(st) >= 4:
            alt = st[:-1] + "y" if st.endswith("i") else st
            if any(t.startswith(st) or t.startswith(alt) for t in toks if len(t) >= 4):
                return True
    return False


_RU_WORD = re.compile(r"[а-яё]+", re.I)


def ru_mentions(text: str, terms: set[str] | list[str]) -> bool:
    """True if a Russian text contains (a form of) one of the given one-word translations:
    «молодая собака» mentions «собака», so it must not stand next to the word "dog"."""
    toks = [t.lower() for t in _RU_WORD.findall(text)]
    for term in terms:
        term = term.lower().strip()
        if " " in term or len(term) < 4:
            continue
        st = term[: max(4, len(term) - 2)]
        if any(t.startswith(st) for t in toks):
            return True
    return False


def load_frequency(path) -> dict[str, int]:
    """Word -> frequency rank (0 = most frequent) from a FrequencyWords list."""
    ranks: dict[str, int] = {}
    with open(path, encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            word = line.split(" ", 1)[0].strip().lower()
            if word and word not in ranks:
                ranks[word] = i
    return ranks


def rank_ru_terms(terms: list[str], freq: dict[str, int] | None, limit: int = 3) -> list[str]:
    """Most common, single-word translations first (source order breaks ties)."""
    if not freq:
        return terms[:limit]
    unknown = len(freq) + 1

    def key(item):
        pos, term = item
        words = term.split()
        rank = max(freq.get(w.strip("-").lower(), unknown) for w in words)
        return (rank + (len(words) - 1) * 20000, pos)

    return [t for _, t in sorted(enumerate(terms), key=key)[:limit]]


def clean_ru_terms(trans_list: str, limit: int = 12) -> list[str]:
    seen: dict[str, None] = {}
    for raw in trans_list.split("|"):
        term = strip_stress(raw.strip())
        if not term or "[" in term or "{" in term or not _CYR.match(term):
            continue
        if len(term) > 30:
            continue
        seen.setdefault(term.lower(), None)
        if len(seen) >= limit:
            break
    return list(seen)


# Real vocabulary that learners still meet as *answers*, but never as random wrong options:
# profanity, sexual and insulting words look offensive in an unrelated sentence or question
# ("Erasmus Darwin was a ___ man" → goddamn / gay). (lemma, pos); pos None = every part of speech.
SENSITIVE: frozenset[tuple[str, str | None]] = frozenset({
    *((w, None) for w in (
        "goddamn", "damn", "damned", "hell", "crap", "shit", "piss", "pee", "fuck", "bitch", "bastard", "arse",
        "ass", "bum", "butt", "prick", "dick", "suck", "sex", "sexual", "sexy", "naked", "nude", "porn",
        "pornography", "rape", "rapist", "whore", "slut", "gay", "lesbian", "retard", "idiot", "moron", "stupid",
        "bugger", "sod")),
    ("bloody", "adjective"), ("bloody", "adverb"), ("screw", "verb"),
})


def sensitive(lemma: str, pos: str) -> bool:
    w = lemma.lower()
    return (w, None) in SENSITIVE or (w, pos) in SENSITIVE
