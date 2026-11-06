"""Dev helper: fill data/gap_lm.json from pickled entries (see dump_entries.py)."""
import pickle
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lexi_pipeline.build import LM_DIR, default_zipf, similarity_for  # noqa: E402
from lexi_pipeline.gapfill import GapIndex, GapLM  # noqa: E402
from lexi_pipeline.wordnet_source import WordNetSource  # noqa: E402

d = pickle.load(open("/tmp/entries.pkl", "rb"))
lm = GapLM(model_dir=LM_DIR)
t = time.time()
for deck in ("general", "tech"):
    usable = [e for e in d[deck] if e.definitions and e.group]
    lm.judge(GapIndex(usable, default_zipf(), lm, similarity_for(WordNetSource())), d[deck],
             progress=lambda a, b: a % 480 == 0 and print(deck, a, b, round(time.time() - t), flush=True))
lm.save()
print("done", round(time.time() - t), len(lm.data))
