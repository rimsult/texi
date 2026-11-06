"""Dev check: how the rewrite handles the learner definitions that used to contain "___"."""
import json, random, re, sys
from collections import Counter
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lexi_pipeline.simple_wiktionary import SimpleWiktionary, learner_definition, head_forms, _form_pattern  # noqa

lx = json.loads((ROOT / "probe/lexicon_before.json").read_text())
targets = []
for e in lx:
    en = [d for d in e["definitions"] if d["lang"] == "en"]
    if not en: continue
    best = max(en, key=lambda d: d["quality"])
    if "___" in best["text"]:
        targets.append((e, best["text"]))
sw = SimpleWiktionary.load(ROOT / "raw/simple-extract.jsonl.gz", {e["lemma"].lower() for e, _ in targets})
def norm(t): return re.sub(r"\W+", " ", t.lower()).strip()
res = Counter(); rows = []
for e, old in targets:
    se = sw.get(e["lemma"], e["pos"])
    if not se: res["no_entry"] += 1; continue
    pat = _form_pattern(head_forms(se.word, se.forms))
    sense = None
    for s in se.senses:
        g = re.sub(pat, "___", s.gloss, flags=re.I)
        if norm(old.split(";")[0])[:25] in norm(g): sense = s; break
    if not sense: res["sense_not_found"] += 1; continue
    new = learner_definition(sense.gloss, se.word, se.forms, pos=se.pos)
    res["ok" if new else "none"] += 1
    rows.append((e["level"], e["lemma"], e["pos"], old, new))
print(len(targets), res)
by = Counter((r[0], r[4] is not None) for r in rows)
for l in ["A1","A2","B1","B2"]: print(l, by[(l,True)], by[(l,False)])
random.seed(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
for r in random.sample([r for r in rows if r[4]], 30): print(f"{r[1]} ({r[2]}): {r[3]}\n   → {r[4]}")
print("---- failed")
for r in random.sample([r for r in rows if not r[4]], 15): print(f"{r[1]} ({r[2]}): {r[3]}")
if "--fails" in sys.argv:
    c = Counter((r[2], " ".join(r[3].split()[:3])) for r in rows if not r[4])
    for k, v in c.most_common(45): print(v, k)
if "--show" in sys.argv:
    pref = sys.argv[sys.argv.index("--show") + 1]
    for r in [r for r in rows if not r[4] and r[3].startswith(pref)][:8]: print(f"{r[1]} ({r[2]}): {r[3]}")
