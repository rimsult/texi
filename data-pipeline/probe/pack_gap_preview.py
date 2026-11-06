"""Dev helper: print random «Вставьте слово» questions from the built packs.

    python probe/pack_gap_preview.py [seed] [count]
"""
import collections
import json
import random
import sys
from pathlib import Path

PACKS = Path(__file__).resolve().parents[2] / "apps/web/public/packs"
manifest = json.loads((PACKS / "manifest.json").read_text("utf-8"))
rows, counts = [], collections.Counter()
for deck in manifest["decks"]:
    for lvl in deck["levels"]:
        pack = json.loads((PACKS / lvl["file"]).read_text("utf-8"))
        by_id = {e["id"]: e for e in pack["entries"]}
        for q in pack["questions"]:
            if q["trainer"] != "gap-fill":
                continue
            counts[(deck["id"], lvl["level"])] += 1
            e = by_id[q["entryId"]]
            s, t = q["span"]
            rows.append(f"{deck['id'][:4]} {lvl['level']} {e['pos'][:4]:4} {e['example'][:s]}___{e['example'][t:]}"
                        f"  || {' | '.join(q['forms'])}")
print(dict(sorted(counts.items())), "total", sum(counts.values()))
random.seed(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
print("\n".join(random.sample(rows, min(len(rows), int(sys.argv[2]) if len(sys.argv) > 2 else 40))))
