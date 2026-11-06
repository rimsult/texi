"""Dev helper: simulate GapLM thresholds on /tmp/gapcal.pkl (see gap_calibrate.py)."""
import math
import pickle
import random
import sys

from wordfreq import zipf_frequency

rows = pickle.load(open("/tmp/gapcal.pkl", "rb"))
from transformers import AutoTokenizer  # noqa: E402
tok = AutoTokenizer.from_pretrained("raw/bert-base-uncased")
MEAN = "--mean" in sys.argv
sys.argv = [a for a in sys.argv if a != "--mean"]
prior = lambda w: (max(zipf_frequency(w, "en"), 1.0) - 9) * math.log(10)  # noqa: E731
ceil, ratio, prob = (float(x) for x in (sys.argv[1:4] if len(sys.argv) > 3 else (0.01, 0.01, 0.1)))
show = sys.argv[4] if len(sys.argv) > 4 else ""


def bad(lpa, pa, lp, p):
    return lp is None or lp >= math.log(ceil) or lp >= lpa + math.log(prob) or lp - p >= lpa - pa + math.log(ratio)


tot = rej = 0
by_pos = {}
random.seed(3)
for eid, pos, level, key, ans, forms, (lpa, scores) in rows:
    pa = prior(ans.lower())
    if MEAN:
        lpa /= len(tok(ans.lower(), add_special_tokens=False)["input_ids"])
    verdict = [(f, bad(lpa, pa, scores[f], prior(f.lower()))) for f in forms]
    tot += len(verdict)
    rej += sum(v for _, v in verdict)
    b = by_pos.setdefault(pos, [0, 0])
    b[0] += len(verdict)
    b[1] += sum(v for _, v in verdict)
    if show and (show == pos or show in key):
        acc = [f for f, v in verdict if not v][:5]
        rj = [f for f, v in verdict if v][:6]
        print(f"{level} {key}  [{ans} p={math.exp(lpa):.3g}]\n   ok: {', '.join(acc)}\n   x:  {', '.join(rj)}")
print(f"rejected {rej}/{tot} = {rej / tot:.0%}", {k: f"{v[1] / v[0]:.0%}" for k, v in by_pos.items()},
      {k: sum(1 for r in rows if r[1] == k) for k in by_pos})
