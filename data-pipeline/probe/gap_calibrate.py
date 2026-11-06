"""Dev helper: score the first 40 candidate forms of sample gap questions with BERT
(no thresholds) and save them, to tune the GapLM rule offline: /tmp/gapcal.pkl."""
import pickle
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lexi_pipeline.build import LM_DIR, default_zipf, similarity_for  # noqa: E402
from lexi_pipeline.gapfill import GapIndex, GapLM, find_gap  # noqa: E402
from lexi_pipeline.wordnet_source import WordNetSource  # noqa: E402

d = pickle.load(open("/tmp/entries.pkl", "rb"))
entries = [e for e in d["general"] if e.definitions and e.group]
idx = GapIndex(entries, default_zipf(), None, similarity_for(WordNetSource()))
random.seed(7)
must = {"The two phenomena are ___ connected.", "We drove ___ admiring the view.", "The window was ___ sealed."}
rows = []
for e in random.sample(entries, len(entries)):
    gap = find_gap(e)
    if not gap:
        continue
    key = GapLM.key(e.example, gap)
    if len(rows) < int(sys.argv[1] if len(sys.argv) > 1 else 400) or key in must:
        forms = [f for _, (_, f) in zip(range(40), idx.eligible(e, gap))]
        rows.append((e.id, e.pos, e.level, key, gap.form, forms))
lm = GapLM(Path("/tmp/none.json"), model_dir=LM_DIR)
t = time.time()
scored = lm.score([(k, a, f) for _, _, _, k, a, f in rows])
print(len(rows), round(time.time() - t))
pickle.dump([(*r, s) for r, s in zip(rows, scored)], open("/tmp/gapcal.pkl", "wb"))
