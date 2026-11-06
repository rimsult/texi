#!/usr/bin/env bash
# Downloads every open data source used by the pipeline into data-pipeline/raw.
# All sources are free; licenses are listed in README.md and shipped in packs/manifest.json.
set -euo pipefail
cd "$(dirname "$0")/../raw" 2>/dev/null || { mkdir -p "$(dirname "$0")/../raw"; cd "$(dirname "$0")/../raw"; }

OLP=https://raw.githubusercontent.com/openlanguageprofiles/olp-en-cefrj/master
curl -fsSLO "$OLP/cefrj-vocabulary-profile-1.5.csv"         # CEFR-J 1.5 (A1–B2)
curl -fsSLO "$OLP/octanove-vocabulary-profile-c1c2-1.0.csv" # Octanove C1/C2, CC BY-SA 4.0
curl -fsSL -o README.md "$OLP/README.md"                    # terms of use
# Wiktionary-derived English→Russian dictionary (WikDict, CC BY-SA 3.0), ~20 MB
curl -fsSL -o wikdict-en-ru.sqlite3 https://download.wikdict.com/dictionaries/sqlite/2/en-ru.sqlite3
# Russian word frequencies (FrequencyWords / OpenSubtitles 2018, CC BY-SA 4.0) to rank translations
curl -fsSL -o ru_50k.txt https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/ru/ru_50k.txt
# Simple English Wiktionary, extracted by wiktextract (kaikki.org), CC BY-SA 4.0, ~5 MB:
# learner definitions in basic English + examples (A1–B1 words, see lexi_pipeline/adapt.py)
curl -fsSL -o simple-extract.jsonl.gz https://kaikki.org/dictionary/downloads/simple/simple-extract.jsonl.gz

python3 - <<'PY'
import nltk
for pkg in ("wordnet", "omw-1.4"):
    nltk.download(pkg, quiet=True)
print("WordNet ready")
PY
ls -la
