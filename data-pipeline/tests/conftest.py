import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lexi_pipeline.models import Definition, Entry  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
PACKS = Path(__file__).resolve().parents[2] / "apps" / "web" / "public" / "packs"


def make_entry(id, lemma, pos="noun", level="A1", group="noun.animal", en=None, ru=None, **kw):
    defs = []
    if en:
        defs.append(Definition(en, "en", kw.pop("source", "wordnet"), kw.pop("quality", 0.9)))
    if ru:
        defs.append(Definition(ru, "ru", "machine", 0.7))
    return Entry(id=id, lemma=lemma, pos=pos, level=level, group=group, definitions=defs,
                 senses=set(kw.pop("senses", {f"{lemma}.n.01"})), synonyms=set(kw.pop("synonyms", {lemma})),
                 ru_terms=set(kw.pop("ru_terms", set())), variants=kw.pop("variants", [lemma]), **kw)


@pytest.fixture
def entry():
    return make_entry


@pytest.fixture
def mini_raw(tmp_path):
    """A tiny but real raw/ directory: CEFR CSVs + a WikDict-shaped SQLite file."""
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "cefrj-vocabulary-profile-1.5.csv").write_text((FIXTURES / "mini_cefrj.csv").read_text())
    (raw / "octanove-vocabulary-profile-c1c2-1.0.csv").write_text("headword,pos,CEFR,notes\n")
    db = sqlite3.connect(raw / "wikdict-en-ru.sqlite3")
    db.execute("CREATE TABLE translation(lexentry, sense_num, sense, written_rep TEXT, trans_list, score, is_good, importance)")
    rows = [line.split("\t") for line in (FIXTURES / "mini_wikdict.tsv").read_text().strip().splitlines()]
    db.executemany("INSERT INTO translation VALUES (?, NULL, ?, ?, ?, ?, 1, 1)",
                   [(f"eng/{w}__{p}__1", s, w, t, float(sc)) for w, p, s, t, sc in rows])
    db.commit()
    db.close()
    return raw
