"""Dev helper: build gap-fill questions from pickled entries and print samples."""
import collections
import pickle
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lexi_pipeline.build import default_zipf, similarity_for  # noqa: E402
from lexi_pipeline.gapfill import GapIndex, GapLM  # noqa: E402
from lexi_pipeline.wordnet_source import WordNetSource  # noqa: E402

d = pickle.load(open("/tmp/entries.pkl", "rb"))
wn = WordNetSource()
lm = GapLM()
out = []
for deck in ("general", "tech"):
    usable = [e for e in d[deck] if e.definitions and e.group]
    idx = GapIndex(usable, default_zipf(), lm, similarity_for(wn))
    for e in d[deck]:
        if e.definitions and (q := idx.build_question(e)):
            out.append((e, q))
c = collections.Counter((q.status, e.level) for e, q in out)
print(sorted(c.items()))
by = {e.id: e for deck in d.values() for e in deck}
random.seed(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
ok = [(e, q) for e, q in out if q.status == "ok"]
for e, q in random.sample(ok, 40):
    s, t = q.span
    print(f"{e.level} {e.pos:9} {e.example[:s]}___{e.example[t:]}  || {' | '.join(q.forms)}")
pickle.dump([(e.id, q) for e, q in out], open("/tmp/gapq.pkl", "wb"))
