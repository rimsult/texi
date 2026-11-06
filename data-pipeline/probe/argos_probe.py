"""Argos-only translations of the probe set."""
import json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from lexi_pipeline.mt import choose, ctranslate2_backend, model_dir, source_variants  # noqa: E402

items = json.loads((HERE / "probe_set.json").read_text("utf-8"))
run = ctranslate2_backend(model_dir())
out = {}
for k in range(0, len(items), 32):
    chunk = items[k:k + 32]
    variants = [source_variants(i["en"], i["pos"]) for i in chunk]
    flat = [(j, s) for j, vs in enumerate(variants) for s in vs]
    hyps = {j: [] for j in range(len(chunk))}
    for (j, _), h in zip(flat, run([s for _, s in flat])):
        hyps[j].extend(h)
    for j, i in enumerate(chunk):
        out[i["key"]] = choose(i["en"], i["pos"], hyps[j])
(HERE / "argos_result.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
print(len(out), "->", HERE / "argos_result.json")
