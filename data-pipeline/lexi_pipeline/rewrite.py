"""Learner definitions without the headword.

Simple English Wiktionary explains words Cobuild-style, in a full sentence that uses the word
itself: "If you carry something, you lift it up and move it to another place." Hiding the word
as "___" turned a meaning question into a fill-in-the-gap one, so the frame is rewritten into
dictionary form instead — by part of speech:

* verb:      "if you ___ something, you lift it up…"       → "to lift something up…"
* adjective: "when something is ___, it is not easy"       → "not easy"
             "if someone is ___, they know how to do it"    → "someone who knows how to do it"
* adverb:    "if something is done ___, it is done with…"  → "with…"
* noun:      "the ___ of something is the place where…"    → "the place where…"

A later clause that still needs the word ("…; 100 ___ is one meter") is dropped. When the
main clause cannot be rewritten the caller falls back to the WordNet definition.
"""
from __future__ import annotations

import functools
import re

BLANK = "___"
_B = re.escape(BLANK)

# Subjects of the "if …" clause and pronouns that pick them up in the main clause.
_PERSON = {"you", "someone", "somebody", "a person", "people", "the person", "he", "she", "they", "we", "i",
           "a man", "a woman", "a child", "anyone", "everyone"}
_PRON = ("the person", "the thing", "then it", "then they", "then you", "then he", "then she",
         "its", "their", "it", "they", "he", "she", "you", "we", "i", "this", "that", "someone", "something",
         "somebody", "x")
_COPULA = {"is", "are", "am", "was", "were", "be"}
_LINKING = {"feel", "feels", "look", "looks", "seem", "seems", "sound", "sounds", "taste", "tastes", "smell",
            "smells", "get", "gets", "become", "becomes", "stay", "stays", "keep", "keeps"} | _COPULA
_INTENS = {"very", "really", "not", "too", "quite", "a bit", "so", "rather", "always", "usually", "often"}
_MODAL_OK = {"can": "be able to", "could": "be able to"}
_PRE_VERB = {"or", "and", "always", "often", "usually", "also", "just", "only", "never", "sometimes", "still",
             "really", "even", "then", "first", "almost"}
_NEG = re.compile(r"^(?:do not|don't|does not|doesn't|did not|didn't)\s+")
_MAIN_LEAD = re.compile(r"^(?:then\s+|that\s+means\s+(?:that\s+)?|it\s+means\s+(?:that\s+)?|this\s+means\s+(?:that\s+)?)")


@functools.lru_cache(maxsize=20000)
def _lemma(word: str) -> str:
    irregular = {"is": "be", "are": "be", "am": "be", "was": "be", "were": "be", "has": "have", "does": "do",
                 "goes": "go", "doesn't": "not"}
    if word in irregular:
        return irregular[word]
    try:
        from lemminflect import getLemma
        lem = getLemma(word, upos="VERB")
        return lem[0] if lem else word
    except ImportError:  # pragma: no cover - lemminflect is in requirements.txt
        if word.endswith("ies"):
            return word[:-3] + "y"
        if re.search(r"(ches|shes|sses|xes|zes|oes)$", word):
            return word[:-2]
        return word[:-1] if word.endswith("s") and not word.endswith("ss") else word


@functools.lru_cache(maxsize=20000)
def _third(word: str) -> str:
    irregular = {"are": "is", "am": "is", "were": "was", "have": "has", "do": "does", "go": "goes",
                 "don't": "doesn't", "be": "is"}
    if word in irregular:
        return irregular[word]
    if word in {"can", "could", "will", "would", "may", "might", "must", "should", "is", "was", "has", "does"}:
        return word
    if _lemma(word) != word:  # already inflected: "did", "knows"
        return word
    try:
        from lemminflect import getInflection
        out = getInflection(word, tag="VBZ")
        return out[0] if out else word
    except ImportError:  # pragma: no cover
        return word + "es" if re.search(r"(ch|sh|ss|x|z|o)$", word) else word + "s"


def _subject(cond: str) -> str:
    """ "you can ___ something" → "you"; "a person is very ___" → "a person"."""
    words = cond.split(BLANK)[0].split()
    skip = _LINKING | _INTENS | {"can", "could", "do", "does", "did", "a", "an", "not", "have", "has", "had", "make",
                                 "makes", "take", "takes", "some", "the"}
    while words and words[-1] in skip:
        words.pop()
    return " ".join(words)


def _split_condition(part: str) -> tuple[str, str] | None:
    """ "if you ___ something, you lift it" → ("you ___ something", "you lift it").

    The main clause is the first one that starts with a pronoun for the subject: in "if you own
    something it belongs to you, it is yours" that is "it belongs to you" — no comma before it."""
    m = re.match(r"^(?:if|when|whenever)\s+(.+)$", part)
    if not m:
        return None
    body = m.group(1)
    i = body.find(BLANK)
    if i < 0:
        return None
    cuts = [(c, c + 1) for c in (x.start() for x in re.finditer(",", body)) if c > i]
    cuts += [(i + len(BLANK) + x.start(), i + len(BLANK) + x.start())
             for x in re.finditer(r"\s(?=(?:then |it |they |he |she |you |that means )\S)", body[i + len(BLANK):])]
    cuts.sort()
    options = []
    for end_cond, start_main in cuts:
        cond, main = body[:end_cond].strip(), _MAIN_LEAD.sub("", body[start_main:].strip()).strip()
        sp = _strip_pronoun(main)
        options.append((cond, main, sp is not None and _agrees(_subject(cond), sp[0])))
    if not options:
        return None
    agreeing = [o for o in options if o[2]]
    if agreeing:
        return agreeing[0][:2]
    # "if something is ___, people like to look at it": no pronoun subject at all is fine for some
    # rewrites; a main clause about something else ("…, it is yours") never is
    bare = [o for o in options if _strip_pronoun(o[1]) is None]
    return bare[0][:2] if bare else None


def _strip_pronoun(main: str) -> tuple[str, str] | None:
    for p in _PRON:
        if main == p or main.startswith(p + " "):
            return p.replace("then ", ""), main[len(p):].strip()
    return None


def _substitute_object(rest: str, obj: str) -> str:
    """ "lift it up and move it" + object "something" → "lift something up and move it";
    "create it" + "a book, an article…" → "create a book, an article…"; "live there" + "somewhere"."""
    obj = obj.strip(" ,")
    if re.match(r"^somewhere\b", obj):
        return re.sub(r"\bthere\b", "somewhere", rest, count=1)
    if re.search(r"\bsomething\b", obj) and not re.search(r"\bsomeone\b", obj):
        return re.sub(r"\bit\b", "something", rest, count=1)
    if re.match(r"^(someone|somebody|a person)\b", obj) and "something" not in obj:
        return re.sub(r"\b(them|him|her)\b", "someone", rest, count=1)
    if re.match(r"^(a|an|the|your|some)\s", obj) and "," not in rest and len(obj.split()) <= 14:
        return re.sub(r"\b(it|them)\b", obj, rest, count=1)
    return rest


def _infinitive(rest: str) -> str | None:
    """ "lifts it up" → "to lift it up"; "don't hit it" → "not to hit it"; "can see" → "to be able to see"."""
    neg = _NEG.match(rest)
    if neg:
        rest = rest[neg.end():]
    words = rest.split()
    if not words:
        return None
    # "partly or completely destroys it": adverbs before the verb stay, the verb loses its -s
    k = 0
    while k < len(words) - 1 and (words[k].endswith("ly") or words[k] in _PRE_VERB):
        k += 1
    first = words[k]
    if first in _MODAL_OK:
        verb = _MODAL_OK[first]
    elif first in {"will", "would", "may", "might", "must", "should", "shall"}:
        return None
    else:
        verb = _lemma(first)
    out = " ".join([*words[:k], verb, *words[k + 1:]])
    return ("not to " if neg else "to ") + out


def _who(rest: str, pron: str) -> str:
    """ "they know how to do it" → "knows how to do it" (for "someone who …")."""
    if pron in {"they", "you", "we", "i", "people"}:
        first, _, tail = rest.partition(" ")
        if first in {"don't", "do"} and tail.startswith("not "):
            return "does " + tail
        tail = re.sub(r"\b(or|and) are\b", r"\1 is", re.sub(r"\b(or|and) have\b", r"\1 has", tail))
        return f"{_third(first)} {tail}".strip()
    return rest


def _verb(cond: str, main: str) -> str | None:
    m = re.match(rf"^(?P<subj>.+?)\s+(?:(?:can|could|do|does|did)\s+)?{_B}(?P<obj>(?:\s.*)?)$", cond)
    if not m or BLANK in m.group("obj"):
        return None
    if re.search(r"\b(?:is|are|am|was|were|be|been|being)$", m.group("subj")):
        return None  # "someone is ___ when they…": a progressive or passive frame
    sp = _strip_pronoun(main)
    if not sp:
        return None
    _, rest = sp
    out = _infinitive(_substitute_object(rest, m.group("obj").strip()))
    return out


_THING_PRON = {"it", "they", "this", "that", "the thing", "its", "something"}
_PERSON_PRON = {"they", "he", "she", "the person", "their", "someone", "somebody"}


def _agrees(subj: str, pron: str) -> bool:
    """The main clause must be about the subject of the condition: in "if you are ___ with
    something, it is not as good as…" the main clause describes the thing, not you."""
    if subj in {"you", "we", "i"}:
        return pron == subj
    if "someone" in subj and "something" in subj:  # "if something or someone is ___, it …"
        return pron in _THING_PRON | _PERSON_PRON
    if subj in _PERSON or re.match(r"^[A-Z][a-z]+$", subj):
        return pron in _PERSON_PRON
    return pron in _THING_PRON


def _adjective(cond: str, main: str) -> str | None:
    m = re.match(rf"^(?P<subj>.+?)\s+(?P<link>{'|'.join(sorted(_LINKING, key=len, reverse=True))})"
                 rf"(?P<adv>(?:\s+(?:{'|'.join(_INTENS)}))*)\s+(?:(?:a|an)\s+)?{_B}"
                 rf"(?P<post>(?:\s[^,]*)?)$", cond)
    if not m:
        return None
    subj = m.group("subj")
    sp = _strip_pronoun(main)
    if not sp:
        if subj not in _PERSON and re.search(r"\s(?:at|to|with|for|about|on)?\s?it$", main) and " " in main:
            return "something that " + re.sub(r"\s+it$", "", main)
        return None
    pron, rest = sp
    if not _agrees(subj, pron):
        return None
    first, _, tail = rest.partition(" ")
    person = subj in _PERSON or pron in {"they", "he", "she", "you", "the person", "someone", "somebody", "their"}
    if pron in {"its", "their"}:  # "if something is ___, its temperature is between…"
        out = ("someone whose " if pron == "their" else "something whose ") + rest
    elif first in _COPULA and m.group("link") in _COPULA or first == m.group("link"):
        out = re.sub(r"\band (?:is|are) ", "and ", tail)  # "not friendly and is mean" → "not friendly and mean"
    elif person:
        out = "someone who " + _who(rest, pron)
    elif pron in {"it", "this", "that", "the thing", "something"}:
        out = "something that " + rest
    else:
        return None
    return out or None


def _adverb(cond: str, main: str) -> str | None:
    m = re.match(rf"^(?P<subj>.+?)\s+(?P<pre>(?:\S+\s+){{0,3}}?){_B}(?P<post>(?:\s[^,]*)?)$", cond)
    if not m:
        return None
    sp = _strip_pronoun(main)
    if not sp:
        return None
    _, rest = sp
    pre = m.group("pre").strip() or m.group("post").strip()  # "if something ___ happens, it happens…"
    pre_it = re.sub(r"\bsomething\b", "it", re.sub(r"\bsomeone\b", "them", pre))
    for p in {pre, pre_it}:
        if p and rest.startswith(p + " "):
            out = rest[len(p):].strip()
            return out or None
    return None


def _noun(part: str) -> str | None:
    pats = (
        rf"^(?:(?:a|an|the|two|some|one)\s+)?{_B}\s+(?:is|are)\s+(?P<rest>(?:when|where|what|how)\s.+)$",
        rf"^(?:the|a|an)\s+{_B}\s+of\s+[^,]+?,?\s+(?:is|are)\s+(?P<rest>.+)$",
        rf"^(?:something|someone|somebody|a\s+\w+|the\s+\w+)'s\s+{_B}\s+(?:is|are)\s+(?P<rest>.+)$",
        rf"^(?:two|some|many)\s+{_B}\s+(?:is|are)\s+(?P<rest>.+)$",
        # "___ refers to the traits that…" → "the traits that…"
        rf"^{_B}\s+refers\s+to\s+(?P<rest>.+)$",
        # a stray headword before the real gloss: "a ___ the act of asking for something"
        rf"^(?:a|an|the)\s+{_B}\s+(?P<rest>(?:the|a|an)\s+(?:act|state|process|way|thing|person|place|time)\s.+)$",
    )
    for p in pats:
        m = re.match(p, part)
        if m:
            return m.group("rest")
    # "___, such as shirts, pants, socks, etc. are things that people wear" →
    # "things that people wear, such as shirts, pants, socks, etc."
    m = re.match(rf"^{_B},\s+(?P<ex>such as\s.+?),?\s+(?:is|are)\s+(?P<rest>.+)$", part)
    return f"{m.group('rest')}, {m.group('ex')}" if m else None


def _to_means(part: str, pos: str) -> str | None:
    """ "to ___ (something) means to …" / "to be ___ means that someone is …"."""
    m = re.match(rf"^to\s+(?:be\s+)?{_B}(?:\s+(?:something|someone|somebody|someone or something|something or someone))?"
                 rf"\s+(?:means|is)\s+(?P<rest>.+)$", part)
    if not m:
        return None
    rest = m.group("rest")
    if pos == "verb":
        obj = re.search(r"\b(something|someone|somebody)\b", part.split(" means ")[0].split(" is ")[0])
        return _substitute_object(rest, obj.group(1)) if rest.startswith("to ") and obj else (
            rest if rest.startswith("to ") else None)
    mm = re.match(r"^(?:that\s+)?(?:someone|something|you|a person|it)\s+(?:is|are)\s+(.+)$", rest)
    if mm:
        return mm.group(1)
    return rest if pos == "adjective" and rest.startswith(("to be ", "being ", "having ", "not ")) else None


def _is_when(part: str, pos: str) -> str | None:
    """ "someone is ___ if they are sure" → "sure"."""
    m = re.match(rf"^(?:someone|something|a person|you)\s+(?:is|are)\s+{_B}\s+(?:if|when)\s+(?P<main>.+)$", part)
    if not m or pos != "adjective":
        return None
    sp = _strip_pronoun(m.group("main"))
    if not sp:
        return None
    first, _, tail = sp[1].partition(" ")
    return tail if first in _COPULA else None


_PREP = {"in", "at", "on", "to", "of", "for", "with", "by", "from", "about", "as", "than", "and", "or", "if", "when"}


def _relative(part: str) -> str | None:
    """ "something that is ___ has no mistakes" → "something that has no mistakes";
    "something that is ___ is high in temperature" → "high in temperature"."""
    m = re.match(rf"^(?P<subj>something|someone|somebody|a person|a thing|anything|anyone|people|things)\s+"
                 rf"(?P<rel>that|who)\s+(?:is|are)\s+{_B}\s+(?P<rest>.+)$", part)
    if not m:
        return None
    rest = m.group("rest")
    first, _, tail = rest.partition(" ")
    if first in {"is", "are"}:
        return tail
    if first in _PREP or not tail:
        return None
    return f"{m.group('subj')} {m.group('rel')} {rest}"


def _attributive(part: str) -> str | None:
    """ "a ___ person is someone who is not sick" → "someone who is not sick";
    "the ___ thing is the last one" → "the last one"; "a ___ person has much knowledge" →
    "someone who has much knowledge"."""
    # "a ___ problem, issue, activity or other thing is about money or business" → "about money…"
    m = re.match(rf"^(?:a|an|the|some)\s+{_B}\s+[a-z ,]+?\s+(?:is|are)\s+"
                 rf"(?P<rest>(?:about|related to|relating to|connected with|used for)\s.+)$", part)
    if m:
        return m.group("rest")
    m = re.match(rf"^(?:a|an|the|some)\s+{_B}\s+(?P<noun>person or thing|thing or person|person|thing|object|place|man|"
                 rf"woman|people|things|one)\s+(?P<rest>.+)$", part)
    if not m:
        return None
    rest, noun = m.group("rest"), m.group("noun")
    first, _, tail = rest.partition(" ")
    if first in {"is", "are"}:
        return tail or None
    if first in _PREP:
        return None
    who = "someone who" if noun in {"person", "man", "woman", "people", "person or thing"} else "something that"
    return f"{who} {_who(rest, 'they') if noun in ('people', 'things') else rest}"


def _use(part: str) -> str | None:
    """ "you use ___ to add surprising information" → "used to add surprising information"."""
    m = re.match(rf"^(?:you|we|people)\s+(?:can\s+)?use\s+{_B}\s+(?P<rest>(?:to|when|for|before|after|in)\s.+)$", part)
    return "used " + m.group("rest") if m else None


def _have_noun(cond: str, main: str) -> str | None:
    """ "when you have ___, you feel hungry" → "what you have when you feel hungry"."""
    m = re.match(rf"^(?P<s>you|someone|a person|people)\s+(?P<v>have|has|feel|feels|get|gets|make|makes|take|takes)\s+"
                 rf"(?:(?:a|an|some|the)\s+)?{_B}(?P<post>(?:\s[^,]*)?)$", cond)
    if not m or not _strip_pronoun(main):
        return None
    return f"what {m.group('s')} {m.group('v')}{m.group('post')} when {main}"


_CONTRACTIONS = {"it's": "it is", "they're": "they are", "you're": "you are", "he's": "he is", "she's": "she is",
                 "that's": "that is", "there's": "there is"}


def rewrite(part: str, pos: str | None) -> str | None:
    """One clause of a learner definition with the headword masked → the same meaning without
    it, or None. A clause without the blank comes back unchanged."""
    if BLANK not in part:
        return part
    part = re.sub(r"\b(?:" + "|".join(map(re.escape, _CONTRACTIONS)) + r")(?=\s)",
                  lambda m: _CONTRACTIONS[m.group(0)], part)
    out = _to_means(part, pos or "") or _is_when(part, pos or "") or _use(part)
    if out is None and pos == "noun":
        out = _noun(part)
    if out is None and pos == "adjective":
        out = _relative(part) or _attributive(part)
    if out is None:
        split = _split_condition(part)
        if split:
            cond, main = split
            if pos == "verb":
                out = _verb(cond, main)
            elif pos == "adjective":
                out = _adjective(cond, main)
            elif pos == "adverb":
                out = _adverb(cond, main)
            elif pos == "noun":
                out = _have_noun(cond, main)
    if not out or BLANK in out:
        return None
    out = re.sub(r"\bto to\b", "to", re.sub(r"\s+", " ", out)).strip(" ,;")
    return out or None
