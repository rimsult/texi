"""Generic CEFR wordlist adapter (CEFR-J, Octanove, Oxford-style CSVs: headword,pos,level)."""
from __future__ import annotations

import csv
import re
from pathlib import Path

from .models import LEVELS, SUPPORTED_POS, Entry, level_index

POS_ALIASES = {"vern": "verb", "adj": "adjective", "adv": "adverb", "n": "noun", "v": "verb"}


def lookup_variants(headword: str) -> list[str]:
    """Spelling variants used for dictionary lookups (not shown to users)."""
    out: list[str] = []
    for v in headword.split("/"):
        v = v.strip()
        if not v:
            continue
        for cand in (v, v.replace("-", ""), v.replace("-", " "), v.replace(" ", "")):
            if cand and cand not in out:
                out.append(cand)
    return out


POS_CODES = {"noun": "n", "verb": "v", "adjective": "adj", "adverb": "adv"}


def make_id(lemma: str, pos: str) -> str:
    """Stable, human-readable id, e.g. "ice_cream-n", "quickly-adv"."""
    slug = re.sub(r"[^a-z0-9]+", "_", lemma.lower()).strip("_")
    return f"{slug}-{POS_CODES[pos]}"


def read_cefr_csv(path: Path, level_column: str = "CEFR") -> list[tuple[str, str, str]]:
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            head = (row.get("headword") or "").strip()
            pos = (row.get("pos") or "").strip().lower()
            pos = POS_ALIASES.get(pos, pos)
            level = (row.get(level_column) or "").strip().upper()
            if head and level in LEVELS:
                rows.append((head, pos, level))
    return rows


def build_entries(rows: list[tuple[str, str, str]]) -> tuple[list[Entry], list[dict]]:
    """Dedupe by (lemma, pos), keeping the lowest CEFR level. Returns entries + skipped report."""
    best: dict[tuple[str, str], Entry] = {}
    skipped: list[dict] = []
    for head, pos, level in rows:
        if pos not in SUPPORTED_POS:
            skipped.append({"headword": head, "pos": pos, "level": level, "reason": "unsupported_pos"})
            continue
        variants = lookup_variants(head)
        lemma = head.split("/")[0].strip()
        key = (lemma.lower(), pos)
        current = best.get(key)
        if current is None or level_index(level) < level_index(current.level):
            best[key] = Entry(id=make_id(lemma, pos), lemma=lemma, pos=pos, level=level, variants=variants)
    entries = sorted(best.values(), key=lambda e: (level_index(e.level), e.lemma.lower()))
    seen: set[str] = set()
    for e in entries:  # guarantee unique ids
        base, n = e.id, 2
        while e.id in seen:
            e.id = f"{base}{n}"
            n += 1
        seen.add(e.id)
    return entries, skipped
