"""Wiktionary adapters.

* ``WikDictSource`` reads the WikDict en-ru SQLite export (pre-processed Wiktionary
  dump via DBnary, CC BY-SA). Fast, used by default.
* ``WiktionaryDumpSource`` streams a raw ``enwiktionary-*-pages-articles.xml(.bz2)``
  dump and extracts English definitions plus Russian translations.
Both expose ``senses(lemma, pos) -> list[Sense]``.
"""
from __future__ import annotations

import bz2
import re
import sqlite3
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .text import clean_gloss, clean_ru_terms, tokens

WIKDICT_POS = {"noun": "Noun", "verb": "Verb", "adjective": "Adjective", "adverb": "Adverb"}


@dataclass
class Sense:
    gloss: str | None
    ru_terms: list[str]
    score: float = 0.0
    definitions: list[str] = field(default_factory=list)


def pick_sense(senses: list[Sense], reference: str | None) -> Sense | None:
    """Prefer the sense whose gloss overlaps the reference (WordNet) gloss, then score."""
    usable = [s for s in senses if s.ru_terms]
    if not usable:
        return None
    ref = set(tokens(reference or "")) - {"a", "an", "the", "of", "or", "and", "to", "in", "by", "that"}

    def key(s: Sense):
        overlap = len(ref & set(tokens(s.gloss or ""))) if ref else 0
        return (overlap, s.score)

    return max(usable, key=key)


class WikDictSource:
    def __init__(self, path: Path):
        # Load into memory and index by headword: ~50x faster than scanning the file.
        disk = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        self.conn = sqlite3.connect(":memory:")
        disk.backup(self.conn)
        disk.close()
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_written_rep ON translation(written_rep)")

    def labelled(self) -> dict[tuple[str, str], list[Sense]]:
        """Senses whose gloss starts with a topical label ("computing: …", "(computing) …"), by (lemma, pos)."""
        out: dict[tuple[str, str], list[Sense]] = {}
        rev = {v: k for k, v in WIKDICT_POS.items()}
        rows = self.conn.execute("SELECT written_rep, lexentry, sense, trans_list, score FROM translation "
                                 "WHERE sense LIKE '%:%' OR sense LIKE '(%)%'")
        for word, lexentry, sense, trans, score in rows:
            m = re.search(r"__(Noun|Verb|Adjective|Adverb)__", lexentry or "")
            if not m or not word:
                continue
            out.setdefault((word, rev[m.group(1)]), []).append(
                Sense(gloss=sense, ru_terms=clean_ru_terms(trans or ""), score=float(score or 0)))
        return out

    def senses(self, lemma: str, pos: str) -> list[Sense]:
        rows = self.conn.execute(
            "SELECT sense, trans_list, score FROM translation WHERE written_rep = ? AND instr(lexentry, ?) > 0",
            (lemma, f"__{WIKDICT_POS[pos]}__"),
        )
        out = []
        for sense, trans, score in rows:
            out.append(Sense(gloss=sense, ru_terms=clean_ru_terms(trans or ""), score=float(score or 0)))
        return out


# ---------------------------------------------------------------- raw XML dump
_HEADING = re.compile(r"^(=+)\s*([^=]+?)\s*\1\s*$")
_DUMP_POS = {"Noun": "noun", "Verb": "verb", "Adjective": "adjective", "Adverb": "adverb"}
_TRANS_TOP = re.compile(r"\{\{trans-top\|([^}|]+)")
_RU = re.compile(r"\{\{tt?\+?\|ru\|([^}|]+)")


def strip_wikitext(line: str) -> str:
    text = re.sub(r"\{\{(?:lb|lbl|label|gloss|qualifier|q)\|[^}]*\}\}", "", line)
    text = re.sub(r"\{\{[^}]*\}\}", "", text)
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", text)
    text = text.replace("'''", "").replace("''", "")
    return re.sub(r"\s+", " ", text).strip()


def parse_english_entry(wikitext: str) -> dict[str, list[Sense]]:
    """Extract {pos: [Sense]} from the ==English== section of one Wiktionary page."""
    result: dict[str, list[Sense]] = {}
    in_english, pos, in_trans = False, None, False
    defs: dict[str, list[str]] = {}
    current: Sense | None = None
    for line in wikitext.splitlines():
        m = _HEADING.match(line.strip())
        if m:
            level, title = len(m.group(1)), m.group(2)
            if level == 2:
                in_english = title == "English"
                pos, in_trans = None, False
                continue
            if not in_english:
                continue
            if title in _DUMP_POS:
                pos, in_trans = _DUMP_POS[title], False
            elif title == "Translations":
                in_trans = pos is not None
            elif level <= 4:
                in_trans = False
            continue
        if not in_english or pos is None:
            continue
        if in_trans:
            top = _TRANS_TOP.search(line)
            if top:
                current = Sense(gloss=top.group(1).strip(), ru_terms=[])
                result.setdefault(pos, []).append(current)
            elif current is not None and line.lstrip("*: ").startswith("Russian"):
                current.ru_terms = clean_ru_terms(" | ".join(_RU.findall(line)))
            continue
        if line.startswith("# "):
            text = strip_wikitext(line[2:])
            if text:
                defs.setdefault(pos, []).append(text)
    for p, items in defs.items():
        senses = result.setdefault(p, [])
        if senses:
            senses[0].definitions = items
        else:
            senses.append(Sense(gloss=None, ru_terms=[], definitions=items))
    return result


class WiktionaryDumpSource:
    def __init__(self, path: Path, wanted: set[str] | None = None):
        self.index: dict[tuple[str, str], list[Sense]] = {}
        opener = bz2.open if str(path).endswith(".bz2") else open
        with opener(path, "rb") as fh:
            title = None
            for _, elem in ET.iterparse(fh, events=("end",)):
                tag = elem.tag.rsplit("}", 1)[-1]
                if tag == "title":
                    title = elem.text
                elif tag == "text" and title and (wanted is None or title in wanted):
                    for pos, senses in parse_english_entry(elem.text or "").items():
                        self.index[(title, pos)] = senses
                elif tag == "page":
                    elem.clear()

    def senses(self, lemma: str, pos: str) -> list[Sense]:
        return self.index.get((lemma, pos), [])


def english_fallback(senses: list[Sense]) -> str | None:
    """Best English definition from Wiktionary when WordNet has none."""
    for s in senses:
        for d in s.definitions:
            g = clean_gloss(d)
            if g and len(g.split()) >= 3:
                return g
    for s in sorted(senses, key=lambda s: -s.score):
        g = clean_gloss(s.gloss or "")
        if g and len(g.split()) >= 3:
            return g
    return None
