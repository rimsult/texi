#!/usr/bin/env bash
# Optional: the offline models, needed only for *new* content. Their results are committed
# (translations in data/mt_en_ru.json, gap-fill verdicts in data/gap_lm.json), so a normal
# content build does not need them (`python3 -m lexi_pipeline.build --no-translate`).
#
# Two independent open translation models (no API, no LLM); the build keeps the translation
# they agree on:
#   * Argos Translate en→ru 1.9 (OPUS-trained, CTranslate2; ~100 MB)            — MIT
#   * Facebook FAIR WMT19 en→ru (facebook/wmt19-en-ru, transformers; ~1.2 GB)  — Apache-2.0
# and a masked language model for the «Вставьте слово» trainer (rejects distractors that
# would also fit the gap; not a generative model):
#   * Google BERT base uncased (google-bert/bert-base-uncased; ~440 MB)        — Apache-2.0
# `--argos-only` skips WMT19 and BERT (one MT engine: lower quality, no cross-scoring;
# new gap-fill sentences stay unchecked by the model).
# Optional extra engines: export GOOGLE_TRANSLATE_API_KEY=… (Cloud Translation, 500k chars/month
# free) or DEEPL_AUTH_KEY=… (DeepL API Free); both need the user's own account.
set -euo pipefail
RAW="$(cd "$(dirname "$0")/.." && pwd)/raw"
REQ="$(dirname "$RAW")/requirements-mt.txt"
mkdir -p "$RAW" && cd "$RAW"

NAME=translate-en_ru-1_9
if [ ! -f "$NAME/model/model.bin" ]; then
  curl -fsSL -o "$NAME.argosmodel" "https://argos-net.com/v1/$NAME.argosmodel"  # ~100 MB zip
  python3 -m zipfile -e "$NAME.argosmodel" .
  rm "$NAME.argosmodel"
fi
pip3 install --user -q -r "$REQ"
echo "Argos model ready: $RAW/$NAME"

if [ "${1:-}" != "--argos-only" ]; then
  WMT=wmt19-en-ru
  HF="https://huggingface.co/facebook/$WMT/resolve/main"
  mkdir -p "$WMT"
  for f in config.json generation_config.json tokenizer_config.json merges.txt vocab-src.json vocab-tgt.json \
           model.safetensors; do
    [ -s "$WMT/$f" ] || curl -fL --retry 3 -o "$WMT/$f" "$HF/$f"
  done
  BERT=bert-base-uncased
  HF="https://huggingface.co/google-bert/$BERT/resolve/main"
  mkdir -p "$BERT"
  for f in config.json tokenizer_config.json tokenizer.json vocab.txt model.safetensors LICENSE; do
    [ -s "$BERT/$f" ] || curl -fL --retry 3 -o "$BERT/$f" "$HF/$f"
  done
  # CPU-only PyTorch keeps the download small (no CUDA libraries).
  pip3 install --user -q torch --index-url https://download.pytorch.org/whl/cpu
  pip3 install --user -q "transformers>=4.40" "sacremoses>=0.1"
  echo "WMT19 model ready: $RAW/$WMT"
  echo "BERT model ready: $RAW/$BERT"
fi
