"""Dev helper: run the pipeline (cached translations only) and pickle the final entries."""
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lexi_pipeline import build as B  # noqa: E402

captured = {}
orig = B.build_questions


def capture(entries, wnsrc, *a, **kw):
    captured[entries[0].deck if entries else "x"] = entries
    return []


B.build_questions = capture
B.build(B.ROOT / "raw", Path("/tmp/packs_dev"), Path("/tmp/review_dev"), translate=False)
pickle.dump(captured, open("/tmp/entries.pkl", "wb"))
print({k: len(v) for k, v in captured.items()})
