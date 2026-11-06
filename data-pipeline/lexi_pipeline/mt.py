"""Russian definitions = machine translation of the (learner) English definition.

A bare translation ("dog" -> «собака») does not train understanding, so Russian mode shows
the *full definition* translated into Russian. Translation runs locally with two independent
open models — no paid API, no LLM:

* Argos Translate en→ru 1.9 (OPUS data, run with CTranslate2), MIT;
* Facebook FAIR WMT19 en→ru (the WMT19 news-translation winner, via transformers), Apache-2.0;
* optionally DeepL, when ``DEEPL_AUTH_KEY`` is set (its free API tier needs an account).

Each engine returns several hypotheses, then *every* engine scores *every* candidate (teacher-
forced log-probability per token) and the candidate with the best summed score wins — ensemble
reranking. Independent models rarely make the same mistake: a hallucination ("concerts" →
«консилиумах»), a truncated output or a dropped second sentence is improbable for the engine
that did not produce it. Hypotheses that render the headword with one of its Wiktionary
translations get a small bonus (dictionary as a glossary). Every hypothesis passes strict checks (Cyrillic only,
no repeated words, sane length, expected part-of-speech shape); a definition with no
acceptable translation simply gets no Russian version.

Results are cached in ``data/mt_en_ru.json`` (committed to the repo), so a content build is
reproducible without the models; only new texts need them.
"""
from __future__ import annotations

import functools
import json
import math
import os
import re
from collections import Counter
from pathlib import Path
from typing import Callable, Iterable, Protocol

from .text import ru_mentions

ROOT = Path(__file__).resolve().parents[1]
CACHE_PATH = ROOT / "data" / "mt_en_ru.json"
MODEL_NAME = "translate-en_ru-1_9"
MODEL_URL = "https://argos-net.com/v1/translate-en_ru-1_9.argosmodel"
FSMT_NAME = "wmt19-en-ru"  # https://huggingface.co/facebook/wmt19-en-ru

_LATIN = re.compile(r"[A-Za-z]{2,}")
_WORDS = re.compile(r"[а-яёА-ЯЁ]+(?:-[а-яёА-ЯЁ]+)*")
_INFINITIVE = re.compile(r"^(не\s+)?[а-яё-]+(ть|ться|ти|тись|чь|чься)\b")
_ADJECTIVAL = re.compile(r"^(не\s?)?[а-яё-]+(ый|ий|ой|ая|яя|ое|ее|ые|ие|ого|его|ым|им|ом)(ся)?\b")
_PREPOSITIONAL = re.compile(r"^(с|со|в|во|на|по|из|от|до|без|для|при|под|над|у|о|об|к|ко|за|через|между)\s")
# Leading filler the model adds to fragments ("to reach" -> «Чтобы добраться»).
_STRIP = [re.compile(p, re.I) for p in (r"^(a|an|the)\s+(?=[а-яё])", r"^чтобы\s+", r"^это\s+", r"^(что-то|нечто|кто-то|некто),?\s+(что|кто)\s+",
                                         r"^(что-то|нечто|кто-то|некто),?\s+")]
_ING = re.compile(r"^[a-z]+ing\b")
_PREP = r"in|at|on|to|toward|towards|into|onto|from|by|near|inside|within"


class Backend(Protocol):
    def __call__(self, sources: list[str]) -> list[list[str]]: ...


_SENTENCE = re.compile(r"^(if|when|someone|something|somebody|anyone|anything|you|people|a person)\b", re.I)


def is_sentence(text: str, pos: str) -> bool:
    """Examples and Cobuild-style definitions ("if you run, you go quickly") are full sentences."""
    return pos == "example" or bool(_SENTENCE.match(text.strip())) or " you " in f" {text} "


def sentence_case(text: str) -> str:
    t = text.strip()
    t = t[0].upper() + t[1:] if t else t
    return t if t.endswith((".", "!", "?")) else t + "."


def source_variants(text: str, pos: str) -> list[str]:
    """English inputs to try. Glosses are fragments; a small frame helps the model pick the
    right Russian form (infinitive for verbs, participle/adjective for adjectives).
    Sentences are translated as they are."""
    if is_sentence(text, pos):
        return [sentence_case(text)]
    t = text.strip()
    t = re.sub(r"^of or (relating|pertaining) to ", "relating to ", t)
    t = re.sub(r"^(of|relating to|pertaining to),? or (being|characteristic of) ", r"\2 ", t)
    t = re.sub(r"^(of,? or )?having to do with ", "relating to ", t)
    # "in or at that place": one Russian preposition covers both («в том месте», not «в или в…»)
    t = re.sub(rf"^({_PREP})(?: or (?:{_PREP}))+\b", r"\1", t)
    t = re.sub(r"^of,? or (?=[a-z]+ing\b)", "", t)  # "of or occurring every seven days"
    if pos == "verb":
        return [t if t.startswith("to ") else "to " + t, t]
    if pos == "adjective":
        out = []
        if t.startswith("having "):
            out.append("with " + t[len("having "):])
        elif t.startswith("being "):
            out.append(t[len("being "):])
        elif _ING.match(t):
            out.append("someone " + t)
        return out + [t]
    return [t]


def normalize(ru: str, sentence: bool = False) -> str:
    """Definition style: no final period, lowercase start, no filler. Sentences (examples)
    keep their capital letter and punctuation."""
    if sentence:
        return re.sub(r"\s+", " ", ru).strip()
    s = re.sub(r"\s+", " ", ru).strip().strip(" .;:")
    for p in _STRIP:
        s = p.sub("", s)
    s = s.strip(" ,.;:")
    first = s.split(" ", 1)[0]
    if s and not (len(first) > 1 and first.isupper()):  # keep acronyms (ДНК), lowercase the rest
        s = s[0].lower() + s[1:]
    return s


_DOUBLE = re.compile(r"(?<![а-яё-])([а-яё-]+)(?:,| или| и) \1(?![а-яё-])", re.I)


def _repeats(text: str) -> str | None:
    """``"adjacent"``: «тишина или тишина», «в или в этом месте» (two English synonyms, one Russian
    word); ``"bigram"``: a phrase used twice («силой или силой», «не более; не более»)."""
    if _DOUBLE.search(text):
        return "adjacent"
    words = [w.lower() for w in _WORDS.findall(text)]
    bigrams = list(zip(words, words[1:]))
    return "bigram" if len(set(bigrams)) < len(bigrams) else None


_EN_FUNCTION = {"of", "the", "a", "an", "or", "and", "to", "in", "on", "by", "for", "with", "from", "as", "at",
                "that", "which", "who", "is", "be", "being", "most", "more", "very", "some", "any", "one",
                "no", "not", "than", "other"}


def _en_repeats(text: str, adjacent: bool = False) -> bool:
    """The English repeats itself too: "over and over" (``adjacent``), or any content word
    ("if you aid someone, you help them" → «…помогаете…, …помогаете…» is fine)."""
    low = text.lower()
    if re.search(r"\b([a-z]+)(,| or| and) \1\b", low):
        return True
    if adjacent:
        return False
    words = [w for w in re.findall(r"[a-z]+", low) if w not in _EN_FUNCTION]
    return len(set(words)) < len(words)


_MALE_EN = re.compile(r"\b(man|men|male|males|gentlem[ae]n|husbands?|boys?|fathers?|sons?|brothers?|kings?|princes?|"
                      r"monks?|guys?|he|him|his|uncles?|nephews?|grandfathers?|lords?|sir|mr)\b", re.I)
_FEMALE_EN = re.compile(r"\b(wom[ae]n|females?|lad(y|ies)|wi(fe|ves)|girls?|mothers?|daughters?|sisters?|queens?|"
                        r"princess(es)?|nuns?|she|her|hers|aunts?|nieces?|grandmothers?|mrs|ms|miss)\b", re.I)


def _gender_mismatch(ru: str, en: str) -> bool:
    """"an adult female person" → «взрослый мужчина женского пола»: a man the English never mentions."""
    low = ru.lower()
    return bool((re.search(r"мужчин|мужск", low) and not _MALE_EN.search(en))
                or (re.search(r"женщин|женск", low) and not _FEMALE_EN.search(en)))


def rejection(ru: str, en: str) -> str | None:
    if len(ru) < 2:
        return "empty"
    if _LATIN.search(ru) or re.match(r"[A-Za-z]\b", ru):
        return "untranslated"
    words = [w.lower() for w in _WORDS.findall(ru)]
    if not words:
        return "not_russian"
    kind = _repeats(ru)
    if kind and not _en_repeats(en, adjacent=kind == "adjacent"):
        return "repeated_word"
    if _gender_mismatch(ru, en):
        return "gender"
    ratio = len(ru) / max(1, len(en))
    if not 0.5 <= ratio <= 2.6:
        return "length"
    return None


def _shape_score(ru: str, pos: str) -> int:
    """Higher = the definition starts the way a Russian dictionary entry for this POS would."""
    low = ru.lower()
    if pos == "verb":
        return 2 if _INFINITIVE.match(low) else 0
    if pos == "adjective":
        return 2 if _ADJECTIVAL.match(low) else (1 if _PREPOSITIONAL.match(low) else 0)
    if pos == "noun" and re.match(r"^[а-яё-]+(ую|юю)\b", low):  # accusative: «скрытую информацию»
        return 0
    return 1


def chrf(a: str, b: str, n: int = 3) -> float:
    """Character n-gram F1 (lowercase): how much two translations agree."""
    def grams(t: str) -> Counter:
        t = " " + re.sub(r"\s+", " ", t.lower()).strip(" .") + " "
        return Counter(t[i:i + n] for i in range(len(t) - n + 1))
    ga, gb = grams(a), grams(b)
    common = sum((ga & gb).values())
    if not common:
        return 0.0
    p, r = common / sum(ga.values()), common / sum(gb.values())
    return 2 * p * r / (p + r)


ENGINE_BONUS = {"deepl": 0.2, "google": 0.2}  # optional API engines, preferred when they pass the checks


def _stem_repeats(ru: str, en: str) -> bool:
    """«другие планеты с планетами» for "other suns with planets": a content word twice."""
    stems = [w.lower()[:5] for w in _WORDS.findall(ru) if len(w) >= 5]
    return len(set(stems)) < len(stems) and not _en_repeats(en)


def parts(text: str) -> int:
    """Sentences (and ``;``-separated clauses) in a text: a translation must not lose one."""
    ends = r"[.!?…]+[\"'”»)]*(?=\s+[\"'“«(]*[A-ZА-ЯЁ])"  # "e.g. bread" is not a sentence end
    return len(re.findall(ends + r"|;(?=\s)", text.strip())) + 1


def _collapsed(ru: str, en: str) -> bool:
    """A three-word definition rendered as one word ("day after today" → «послезавтра») is a
    guess at a translation, not a definition — and often the wrong one."""
    n_en = len([w for w in re.findall(r"[A-Za-z]+(?:'[a-z]+)?", en) if w.lower() not in ("a", "an", "the")])
    return n_en >= 3 and len(re.split(r"[\s-]+", ru.strip())) * 2.5 < n_en


def candidates(en: str, pos: str, hypotheses: dict[str, list[str]]) -> list[tuple[str, str, int]]:
    """Acceptable, normalized hypotheses as ``(russian, engine, rank)``, one per text."""
    out: list[tuple[str, str, int]] = []
    keep_doubles = _en_repeats(en, adjacent=True)  # "over and over" → «снова и снова»
    for name, hs in hypotheses.items():
        for i, h in enumerate(hs):
            ru = normalize(h, sentence=pos == "example")
            if not keep_doubles:  # "pleasant, enjoyable" → «приятное, приятное» → «приятное»
                ru = _DOUBLE.sub(r"\1", ru)
            if not rejection(ru, en) and all(ru != c[0] for c in out):
                out.append((ru, name, i))
    return out


def choose(en: str, pos: str, hypotheses: Iterable[str] | dict[str, list[str]],
           glossary: Iterable[str] = (), scores: dict[str, float] | None = None) -> str | None:
    """Best acceptable hypothesis.

    * one engine: correct shape first, then model order;
    * several engines with ``scores`` (every candidate scored by every engine — the summed
      log-probability per token, see :meth:`TranslationCache.translate_missing`): the candidate
      the ensemble finds most likely. A truncated or partial output ("…eaten as a" → «…съеденные
      в качестве») is improbable for the engine that did not make it;
    * several engines without scores: the hypothesis that agrees most with the other engines'
      hypotheses (character n-gram F-score, consensus).

    The POS shape, the glossary (the headword rendered with one of its Wiktionary translations)
    and a repeated content word are small corrections on top."""
    groups = hypotheses if isinstance(hypotheses, dict) else {"mt": list(hypotheses)}
    sentence = is_sentence(en, pos)
    cands = candidates(en, pos, groups)
    if not cands:
        return None
    # Models happily drop a second sentence ("… I can't reach it.") and score it well; whenever
    # some candidate keeps every part, the shorter ones are out.
    complete = [c for c in cands if parts(c[0]) >= parts(en) and not _collapsed(c[0], en)]
    cands = complete or cands
    engines = {name for name, hs in groups.items() if hs}
    terms = [t for t in glossary if t]
    by_engine = {n: {c[0] for c in candidates(en, pos, {n: hs})} for n, hs in groups.items()}

    def score(c: tuple[str, str, int]) -> tuple:
        ru, name, i = c
        shape = 0 if sentence else _shape_score(ru, pos)
        if len(engines) == 1:
            return (shape, -i)
        bonus = (ENGINE_BONUS.get(name, 0.0) + (0.1 if terms and ru_mentions(ru, terms) else 0.0)
                 - (0.15 if _stem_repeats(ru, en) else 0.0) + 0.1 * shape)
        if scores and ru in scores:
            return (scores[ru] + bonus,)
        agree = max((chrf(ru, o) for e in by_engine if ru in by_engine[e]
                     for n, hs in by_engine.items() if n != e for o in hs), default=0.0)
        return (agree + bonus - 0.02 * i,)

    return max(cands, key=score)[0]


class TranslationCache:
    """``"pos|english" -> russian`` (``null`` = no acceptable translation)."""

    def __init__(self, path: Path = CACHE_PATH):
        self.path = path
        self.data: dict[str, str | None] = json.loads(path.read_text("utf-8")) if path.exists() else {}
        self.dirty = False

    @staticmethod
    def key(en: str, pos: str) -> str:
        return f"{pos}|{en}"

    def has(self, en: str, pos: str) -> bool:
        return self.key(en, pos) in self.data

    def get(self, en: str, pos: str) -> str | None:
        return self.data.get(self.key(en, pos))

    def put(self, en: str, pos: str, ru: str | None) -> None:
        self.data[self.key(en, pos)] = ru
        self.dirty = True

    def save(self) -> None:
        if self.dirty:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            body = json.dumps(dict(sorted(self.data.items())), ensure_ascii=False, indent=0)
            self.path.write_text(body + "\n", encoding="utf-8")
            self.dirty = False

    def translate_missing(self, items: Iterable[tuple[str, str]], backend: Backend | dict[str, Backend],
                          batch: int = 32, progress: Callable[[int, int], None] | None = None,
                          glossary: dict[tuple[str, str], Iterable[str]] | None = None) -> int:
        """Translate every item not in the cache yet.

        With several engines, each one scores every candidate (its own and the others'):
        teacher-forced mean log-probability per token; :func:`choose` takes the best sum."""
        backends = backend if isinstance(backend, dict) else {"mt": backend}
        scorers = {n: b.score for n, b in backends.items() if callable(getattr(b, "score", None))}
        # Similar lengths per batch: padding is what makes transformer batches slow.
        todo = sorted({(en, pos) for en, pos in items if not self.has(en, pos)}, key=lambda k: (len(k[0]), k))
        for start in range(0, len(todo), batch):
            chunk = todo[start:start + batch]
            variants = [source_variants(en, pos) for en, pos in chunk]
            sources = [(i, s) for i, vs in enumerate(variants) for s in vs]
            hyps: dict[int, dict[str, list[str]]] = {i: {} for i in range(len(chunk))}
            for name, run in backends.items():
                outs = run([s for _, s in sources])
                for (i, _), out in zip(sources, outs):
                    hyps[i].setdefault(name, []).extend(out)
            scores: dict[int, dict[str, float]] = {i: {} for i in range(len(chunk))}
            if len(backends) > 1 and scorers:
                pairs = [(i, ru) for i, (en, pos) in enumerate(chunk) for ru, _, _ in candidates(en, pos, hyps[i])]
                pairs.sort(key=lambda p: len(p[1]))
                # Scored against the plain definition, not the "someone …" frame used to get a participle.
                src = [next((v for v in vs if not v.startswith("someone ")), vs[0]) for vs in variants]
                for name, fn in scorers.items():
                    for k in range(0, len(pairs), batch):
                        part = pairs[k:k + batch]
                        for (i, ru), lp in zip(part, fn([src[i] for i, _ in part], [ru for _, ru in part])):
                            scores[i][ru] = scores[i].get(ru, 0.0) + lp
            for i, (en, pos) in enumerate(chunk):
                h = hyps[i] if len(backends) > 1 else hyps[i].get(next(iter(backends)), [])
                self.put(en, pos, choose(en, pos, h, (glossary or {}).get((en, pos), ()), scores[i]))
            if progress:
                progress(min(start + batch, len(todo)), len(todo))
            if start // batch % 10 == 9:
                self.save()  # long runs survive interruptions
        self.save()
        return len(todo)


def fsmt_dir() -> Path | None:
    for p in (os.environ.get("LEXI_FSMT_MODEL"), ROOT / "raw" / FSMT_NAME):
        if p and (Path(p) / "config.json").exists():
            return Path(p)
    return None


def fsmt_backend(path: Path, beam: int = 4, hypotheses: int = 2) -> Backend:
    """Facebook FAIR's WMT19 en→ru transformer (``facebook/wmt19-en-ru``) on CPU."""
    import torch
    from transformers import FSMTForConditionalGeneration, FSMTTokenizer

    torch.set_num_threads(os.cpu_count() or 2)
    tok = FSMTTokenizer.from_pretrained(str(path))
    model = FSMTForConditionalGeneration.from_pretrained(str(path)).eval()
    dec = model.model.decoder
    if hasattr(dec, "output_projection"):  # checkpoint ships only the (identical) output projection
        dec.embed_tokens.weight = dec.output_projection.weight
    model.generation_config.max_length = None  # max_new_tokens below decides (and no warning per batch)
    tgt_vocab = {t: i for i, t in tok.decoder.items()}
    eos, pad = model.config.eos_token_id, model.config.pad_token_id
    start = model.generation_config.decoder_start_token_id

    def run(sources: list[str]) -> list[list[str]]:
        with torch.inference_mode():
            batch = tok(sources, return_tensors="pt", padding=True, truncation=True, max_length=256)
            n = int(batch["input_ids"].shape[1])
            out = model.generate(**batch, num_beams=beam, num_return_sequences=hypotheses,
                                 max_new_tokens=min(256, 3 * n + 20))
        ids = out.tolist()
        texts = tok.batch_decode(out, skip_special_tokens=True)
        # A hypothesis that never emitted </s> was cut by the length cap: drop it.
        texts = [t if eos in row[1:] else "" for t, row in zip(texts, ids)]
        return [texts[i * hypotheses:(i + 1) * hypotheses] for i in range(len(sources))]

    unk = tgt_vocab.get(tok.unk_token, 3)

    @functools.lru_cache(maxsize=200_000)
    def segment(word: str) -> tuple[int, ...]:
        """The checkpoint ships only the English BPE merges, so a Russian word is split into the
        fewest target-vocabulary pieces (ties: more frequent pieces) — the same split as the
        model's own output for ~80% of sentences, a near-identical one for the rest."""
        n, inf = len(word), (float("inf"), 0.0)
        best: list[tuple[tuple[float, float], int]] = [((0, 0.0), 0)] + [(inf, 0)] * n
        for i in range(n):
            if best[i][0] == inf:
                continue
            for j in range(i + 1, n + 1):
                tid = tgt_vocab.get(word[i:j] + ("</w>" if j == n else ""))
                if tid is not None:
                    cost = (best[i][0][0] + 1, best[i][0][1] + math.log(tid + 1))
                    if cost < best[j][0]:
                        best[j] = (cost, i)
        if best[n][0] == inf:
            return (unk,)
        out, j = [], n
        while j > 0:
            i = best[j][1]
            out.append(tgt_vocab[word[i:j] + ("</w>" if j == n else "")])
            j = i
        return tuple(reversed(out))

    def encode_ru(text: str) -> list[int]:
        words = tok.moses_tokenize(tok.moses_pipeline(text, lang="ru"), lang="ru")
        return [t for w in words if w for t in segment(w)][:254] + [eos]

    def score(sources: list[str], targets: list[str]) -> list[float]:
        """Mean log-probability per target token (teacher forcing, </s> included)."""
        with torch.inference_mode():
            batch = tok(sources, return_tensors="pt", padding=True, truncation=True, max_length=256)
            tgt = [encode_ru(t) for t in targets]
            width = max(len(t) for t in tgt)
            labels = torch.tensor([t + [pad] * (width - len(t)) for t in tgt])
            dec_in = torch.tensor([[start] + t[:-1] + [pad] * (width - len(t)) for t in tgt])
            logits = model(**batch, decoder_input_ids=dec_in, use_cache=False).logits  # no cache = causal mask
            lp = torch.log_softmax(logits.float(), dim=-1).gather(-1, labels.unsqueeze(-1)).squeeze(-1)
            mask = (labels != pad).float()
            return ((lp * mask).sum(-1) / mask.sum(-1)).tolist()

    run.score = score  # type: ignore[attr-defined]
    return run


def deepl_backend(key: str, opener=None) -> Backend:
    """Optional: DeepL API (free tier keys end with ":fx"). Never required for a build."""
    import urllib.parse
    import urllib.request

    url = "https://api-free.deepl.com/v2/translate" if key.endswith(":fx") else "https://api.deepl.com/v2/translate"
    opener = opener or urllib.request.urlopen

    def run(sources: list[str]) -> list[list[str]]:
        data = urllib.parse.urlencode([("source_lang", "EN"), ("target_lang", "RU"),
                                       *[("text", s) for s in sources]]).encode()
        req = urllib.request.Request(url, data=data, headers={"Authorization": f"DeepL-Auth-Key {key}"})
        with opener(req) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return [[t["text"]] for t in body["translations"]]

    return run


def google_backend(key: str, opener=None) -> Backend:
    """Optional: Google Cloud Translation API v2 (key from the Cloud console; 500 000
    characters a month are free). In our comparison on 250 A1–A2 definitions and
    examples it was better than the offline ensemble in 38% of cases and worse in 6%
    (probe/report.html). Never required for a build; without a key nothing changes."""
    import html
    import urllib.parse
    import urllib.request

    url = "https://translation.googleapis.com/language/translate/v2?" + urllib.parse.urlencode({"key": key})
    opener = opener or urllib.request.urlopen

    def run(sources: list[str]) -> list[list[str]]:
        body = json.dumps({"q": sources, "source": "en", "target": "ru", "format": "text"}).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with opener(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [[html.unescape(t["translatedText"])] for t in data["data"]["translations"]]

    return run


def available_backends() -> dict[str, Backend]:
    """Every engine installed on this machine (none is required when the cache is complete)."""
    out: dict[str, Backend] = {}
    if md := model_dir():
        out["argos"] = ctranslate2_backend(md)
    if fd := fsmt_dir():
        out["wmt19"] = fsmt_backend(fd)
    if key := os.environ.get("DEEPL_AUTH_KEY"):
        out["deepl"] = deepl_backend(key)
    if key := os.environ.get("GOOGLE_TRANSLATE_API_KEY"):
        out["google"] = google_backend(key)
    return out


def model_dir() -> Path | None:
    for p in (os.environ.get("LEXI_MT_MODEL"), ROOT / "raw" / MODEL_NAME):
        if p and (Path(p) / "model" / "model.bin").exists():
            return Path(p)
    return None


def ctranslate2_backend(path: Path, beam: int = 5, hypotheses: int = 3) -> Backend:
    import ctranslate2
    import sentencepiece

    sp = sentencepiece.SentencePieceProcessor(model_file=str(path / "sentencepiece.model"))
    translator = ctranslate2.Translator(str(path / "model"), device="cpu", intra_threads=os.cpu_count() or 2)

    def run(sources: list[str]) -> list[list[str]]:
        res = translator.translate_batch([sp.encode(s, out_type=str) for s in sources], beam_size=beam,
                                         num_hypotheses=hypotheses, max_decoding_length=200)
        return [[sp.decode(h) for h in r.hypotheses] for r in res]

    def score(sources: list[str], targets: list[str]) -> list[float]:
        """Mean log-probability per target token (teacher forcing, </s> included)."""
        res = translator.score_batch([sp.encode(s, out_type=str) for s in sources],
                                     [sp.encode(t, out_type=str)[:250] for t in targets])
        return [sum(r.log_probs) / max(1, len(r.log_probs)) for r in res]

    run.score = score  # type: ignore[attr-defined]
    return run
