"""General-deck expansion: frequent WordNet words that the CEFR lists do not cover.

CEFR-J and Octanove stop at ~9.5k headwords. University-level reading needs more, so the
general deck adds WordNet lemmas that are (a) frequent in modern English (wordfreq), (b)
attested in the sense-tagged SemCor corpus (WordNet sense counts — filters out obscure
and dictionary-only words), (c) not names, inflections, slang, vulgar or archaic usage.
Their level is estimated from frequency, calibrated on the CEFR lists, and never below B2
(an unlisted word is not "elementary"). Specialised terms go to the technical deck instead.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable

from .cefr import make_id
from .models import POS_TO_WN, Entry
from .technical import estimate_level
from .text import clean_gloss, leaks

Zipf = Callable[[str], float]

MIN_ZIPF = 2.8  # words tagged at least twice in SemCor
MIN_ZIPF_SINGLE = 3.2  # words tagged once must be more frequent
MIN_COUNT = 2
MAX_WORDS = 4000
LEVEL_FLOOR = "B2"
# WordNet usage domains that are not material for a learner's general deck.
EXCLUDED_USAGE = {
    "colloquialism.n.01", "slang.n.02", "archaism.n.01", "disparagement.n.01", "ethnic_slur.n.01",
    "obscenity.n.02", "vulgarism.n.01", "trademark.n.02", "trade_name.n.01", "plural.n.01",
    "combining_form.n.01", "comparative.n.01", "superlative.n.01", "dialect.n.01", "regionalism.n.01",
    "street_name.n.02", "african_american_vernacular_english.n.01", "yiddish.n.01", "french.n.01",
    "acronym.n.01", "abbreviation.n.01", "euphemism.n.01",
}
# Sensitive words a study app should not drill, even in a neutral sense.
BLOCKLIST = {
    "arse", "ass", "bastard", "bitch", "bollocks", "boob", "bugger", "cock", "crap", "cunt", "damn", "dick",
    "dyke", "fag", "faggot", "fuck", "horny", "jerk", "nigger", "orgasm", "penis", "piss", "porn", "porno",
    "pornography", "prick", "pussy", "rape", "rapist", "retard", "screw", "shit", "slut", "tit", "tits",
    "twat", "vagina", "wank", "whore", "masturbate", "masturbation", "erection", "ejaculate", "sodomy",
    "pimp", "hooker", "prostitute", "prostitution", "nude", "nudity", "naked", "sexy", "erotic", "lust",
    "bullshit", "booze", "booty", "darn", "sucker", "intercourse", "homosexual", "cocaine", "kinda", "cant",
    "lusty", "testicle", "womb", "troll", "hangover",
    # first names and clippings whose frequency comes from another use ("Harry", "Mr Earl")
    "mike", "harry", "bob", "jimmy", "ken", "chuck", "victor", "earl", "sally", "potter", "sterling", "belle",
    "beau", "gal", "chap", "bloke", "tee", "bash", "boo", "rev", "sub", "inter", "ultra", "combo", "champ",
}
_WORD = re.compile(r"^[a-z]{3,}$")


@dataclass(frozen=True)
class ExtraCandidate:
    lemma: str
    pos: str
    count: int  # SemCor sense-tagged occurrences (all senses of this POS)
    zipf: float


def _bases(wn, name: str, wn_pos: str) -> list[str]:
    return list(getattr(wn, "_morphy")(name, wn_pos))


def collect_extra(wn, zipf: Zipf, known: set[str], exclude: Iterable[str] = (),
                  limit: int = MAX_WORDS) -> list[ExtraCandidate]:
    """Most frequent eligible words first; one part of speech per word (the one SemCor
    uses most), so the deck never has two cards for one spelling."""
    exclude = set(exclude) | BLOCKLIST
    best: dict[str, ExtraCandidate] = {}
    for pos, wn_pos in POS_TO_WN.items():
        for name in wn.all_lemma_names(wn_pos):
            if not _WORD.match(name) or name in known or name in exclude:
                continue
            z = zipf(name)
            if z < MIN_ZIPF:
                continue
            syns = wn.synsets(name, wn_pos)
            if not syns or syns[0].instance_hypernyms():
                continue  # names of people, places, works
            lemma = next((l for l in syns[0].lemmas() if l.name().lower() == name), None)
            if lemma is None or lemma.name() != name:
                continue  # capitalised (proper noun) or a different word
            count = sum(l.count() for s in syns for l in s.lemmas() if l.name() == name)
            if count < MIN_COUNT and not (count >= 1 and z >= MIN_ZIPF_SINGLE):
                continue
            if any(d.name() in EXCLUDED_USAGE for s in syns[:2] for d in s.usage_domains()):
                continue
            if any(b != name for b in _bases(wn, name, wn_pos)):
                continue  # inflected form (plural, comparative)
            if any(b != name and b in known for p in "nvar" for b in _bases(wn, name, p)):
                continue  # a form of a listed word: "made", "done", "longer", "curing"
            if any(l.name().lower() == name and l.name() != name for s in wn.synsets(name) for l in s.lemmas()):
                continue  # also a name ("john", "harry"): its frequency is mostly the name
            gloss = clean_gloss(syns[0].definition())
            if not gloss or leaks(gloss, [name]):
                continue  # "oddly" = "in an odd manner" is not worth a card
            cand = ExtraCandidate(name, pos, count, round(z, 2))
            if name not in best or count > best[name].count:
                best[name] = cand
    ranked = sorted(best.values(), key=lambda c: (-c.zipf, c.lemma, c.pos))
    return ranked[:limit]


def extra_entries(cands: Iterable[ExtraCandidate], thresholds: list[float], taken: set[str]) -> list[Entry]:
    out = []
    for c in cands:
        eid = make_id(c.lemma, c.pos)
        if eid in taken:
            continue
        taken.add(eid)
        out.append(Entry(id=eid, lemma=c.lemma, pos=c.pos, level=estimate_level(c.zipf, thresholds, LEVEL_FLOOR),
                         variants=[c.lemma], level_source="frequency"))
    return out
