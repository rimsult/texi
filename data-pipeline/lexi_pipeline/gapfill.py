"""Gap-fill trainer ("Вставьте слово"): the entry's example sentence with the word
blanked out. The options are the target and distractors *in the same grammatical form*
(ate / slept / drank), so grammar alone never gives the answer away. Nouns, verbs and
adjectives only: almost any adverb fits a sentence ("The judge sat there ___").

Rules for a distractor (besides the usual: same part of speech, ±1 CEFR level):

* a different semantic group and, for adjectives, a different antonym family
  (hot / cold would both fit "The soup is ___");
* never a synonym, a shared sense or translation, or a hypernym (dog / animal);
* its inflected form is a real word (lemminflect + wordfreq: no "beautifuler",
  no "more big") and no form of it already occurs in the sentence;
* an offline masked language model (BERT, Apache 2.0) must not consider it a plausible
  fill for the gap — "I ate an ___" rejects "orange" for "apple". The model runs only at
  build time; its verdicts are cached in ``data/gap_lm.json`` so builds are reproducible
  without it.
"""
from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from itertools import islice
from pathlib import Path
from typing import Callable, Iterable, Iterator

from .models import Entry, Question, level_index, stable_order
from .text import leaks, sensitive

TRAINER = "gap-fill"
POOL_SIZE = 5
MIN_DISTRACTORS = 2
SIMILARITY_LIMIT = 0.8
MIN_WORDS = 4
CACHE_PATH = Path(__file__).resolve().parents[1] / "data" / "gap_lm.json"
LM_CEILING = 0.01  # a distractor this likely in the gap always fits too well
LM_RATIO = 0.001  # ... and so does one that fits at least 1/1000 as well as the answer
LM_PROB_RATIO = 0.01  # ... or is at least 1/100 as likely as the answer
ACCEPT_LIMIT = 10  # accepted distractors judged per sentence (a pool needs POOL_SIZE distinct ones)
MAX_TRIED = 200  # candidates per sentence at most: where nearly any word fits, the rest would not pass either
LM_MODEL = "bert-base-uncased"
RULE = (f"{LM_MODEL};mean-pll;pmi+prob;ceiling={LM_CEILING};ratio={LM_RATIO};prob={LM_PROB_RATIO};pieces=3;"
        f"accept={ACCEPT_LIMIT}")
RULE_KEY = "__rule__"

GAP_POS = ("noun", "verb", "adjective")  # an adverb (quickly / solemnly / previously) fits almost anywhere
UPOS = {"noun": "NOUN", "verb": "VERB", "adjective": "ADJ", "adverb": "ADV"}
TAGS = {"noun": ("NN", "NNS"), "verb": ("VB", "VBP", "VBZ", "VBD", "VBN", "VBG")}
BASE_TAG = {"noun": "NN", "verb": "VB", "adjective": "JJ", "adverb": "RB"}
_AUX_PERFECT = {"have", "has", "had", "'ve", "having", "is", "are", "was", "were", "be", "been",
                "being", "am", "'re", "get", "gets", "got", "gotten", "getting"}
_BASE_TRIGGER = {"to", "can", "could", "will", "would", "shall", "should", "may", "might", "must",
                 "do", "does", "did", "don't", "doesn't", "didn't", "won't", "can't", "cannot",
                 "let's", "please", "'ll"}
_SKIP_BACK = {"not", "n't", "never", "just", "already", "ever", "also", "always", "often", "really",
              "only", "still", "even", "almost", "usually", "sometimes", "quickly", "slowly", "all",
              "both", "recently", "finally", "suddenly", "nearly", "probably", "certainly"}
_PERIPHRASTIC = {"more", "most", "less", "least"}
_TOKEN = re.compile(r"[A-Za-z]+(?:'[a-z]+)?")


@lru_cache(maxsize=100_000)
def _inflections(lemma: str, pos: str) -> dict[str, tuple[str, ...]]:
    """Penn tag -> forms (lower case) in lemminflect's order, the usual spelling first.
    Multi-word entries inflect their head (look after → looked after, ice cream → ice creams)."""
    from lemminflect import getAllInflections, getInflection

    words = lemma.lower().split()
    if not words or pos not in UPOS:
        return {}
    head_i = 0 if pos == "verb" else len(words) - 1
    head = words[head_i]
    if pos in ("noun", "verb"):  # regular forms are guessed for unknown words, checked later
        infl = {tag: getInflection(head, tag) for tag in TAGS[pos]} if head.isalpha() else {}
        infl = {t: f for t, f in infl.items() if f}
    elif len(words) == 1:  # only dictionary comparatives: no "beautifuler"
        infl = dict(getAllInflections(head, upos=UPOS[pos]))
    else:
        infl = {}
    infl.setdefault(BASE_TAG[pos], (head,))
    return {tag: tuple(dict.fromkeys(" ".join(words[:head_i] + [f.lower()] + words[head_i + 1:])
                                     for f in forms))
            for tag, forms in infl.items()}


@lru_cache(maxsize=100_000)
def word_forms(lemma: str, pos: str) -> dict[str, frozenset[str]]:
    """form (lower case) -> Penn tags."""
    out: dict[str, set[str]] = defaultdict(set)
    for tag, forms in _inflections(lemma, pos).items():
        for f in forms:
            out[f].add(tag)
    return {f: frozenset(t) for f, t in out.items()}


def preferred_form(lemma: str, pos: str, tag: str) -> str | None:
    """The usual form of a word for a tag: lemminflect lists "colleges" before the
    uncountable "college" as plurals."""
    if tag == BASE_TAG.get(pos):
        return lemma.lower()
    forms = _inflections(lemma, pos).get(tag)
    return forms[0] if forms else None


def _pattern(forms: Iterable[str]) -> re.Pattern:
    alts = "|".join(re.escape(f).replace(r"\ ", r"\s+") for f in sorted(forms, key=len, reverse=True))
    return re.compile(rf"(?<![\w-])(?:{alts})(?![\w-])", re.I)


@dataclass
class Gap:
    start: int
    end: int
    tag: str  # Penn tag the options must take ("JJ+" = adjective after more/most)
    form: str  # the word as written in the sentence

    @property
    def span(self) -> list[int]:
        return [self.start, self.end]


def _context_before(text: str, start: int) -> list[str]:
    toks = [t.lower() for t in _TOKEN.findall(text[:start])]
    return [t for t in toks if t not in _SKIP_BACK][-2:]


def _verb_tag(tags: frozenset[str], text: str, start: int) -> str | None:
    if "VBZ" in tags:
        return "VBZ"
    if "VBG" in tags:
        return "VBG"
    before = _context_before(text, start)
    prev = before[-1] if before else None
    if tags & {"VBD", "VBN"}:
        if prev in _AUX_PERFECT or (prev and prev.endswith(("'ve", "'re"))):
            return "VBN" if "VBN" in tags else None
        if "VB" in tags:  # put / cut / hit: base or past — decide only from clear context
            return "VB" if prev in _BASE_TRIGGER or prev is None else None
        if prev in _BASE_TRIGGER:
            return None  # "to ate"? the sentence is unusual, skip it
        return "VBD" if "VBD" in tags else None
    if "VB" in tags:
        return "VB"
    return "VBP" if "VBP" in tags else None  # are / am


def find_gap(entry: Entry) -> Gap | None:
    """Exactly one occurrence of a form of the word in the example; returns its span and tag."""
    text = entry.example
    if entry.pos not in GAP_POS or not text or len(text.split()) < MIN_WORDS:
        return None
    forms: dict[str, frozenset[str]] = {}
    for head in [entry.lemma, *entry.variants]:
        for f, t in word_forms(head, entry.pos).items():
            forms[f] = forms.get(f, frozenset()) | t
    if not forms:
        return None
    hits = list(_pattern(forms).finditer(text))
    if len(hits) != 1:
        return None
    m = hits[0]
    rest = text[:m.start()] + " " + text[m.end():]
    if leaks(rest, [entry.lemma]):  # "The teacher teaches…": another word gives it away
        return None
    form = re.sub(r"\s+", " ", m.group(0))
    tags = forms.get(form.lower(), frozenset())
    if entry.pos == "verb":
        tag = _verb_tag(tags, text, m.start())
    elif entry.pos == "noun":
        tag = "NN" if "NN" in tags else "NNS" if "NNS" in tags else None
    else:
        base = BASE_TAG[entry.pos]
        for tag in (base, base + "R", base + "S"):
            if tag in tags:
                break
        else:
            tag = None
        if tag == "JJ" and (_context_before(text, m.start())[-1:] or [None])[0] in _PERIPHRASTIC:
            tag = "JJ+"
    if tag is None:
        return None
    return Gap(m.start(), m.end(), tag, form)


def inflect(cand: Entry, gap: Gap, zipf: Callable[[str], float]) -> str | None:
    """The distractor in the gap's grammatical form, or None if that form is not a real word."""
    if gap.tag == "JJ+":
        if preferred_form(cand.lemma, cand.pos, "JJR"):
            return None  # "more big" is wrong, only words without -er may follow "more"
        form = cand.lemma.lower()
    else:
        form = preferred_form(cand.lemma, cand.pos, gap.tag)
    if not form:
        return None
    head = 0 if cand.pos == "verb" else -1
    if form != cand.lemma.lower() and zipf(form.split()[head]) < 1.5:
        return None  # lemminflect guesses regular forms; keep only attested ones
    if gap.tag == "NNS" and (form == cand.lemma.lower()
                             or zipf(form.split()[head]) < zipf(cand.lemma.lower().split()[head]) - 2):
        return None  # uncountable: "informations", "advices" are not plurals one would use
    if gap.form[:1].isupper():
        form = form[:1].upper() + form[1:]
    return form


class GapLM:
    """Masked-LM plausibility of words in a gap, judged per masked sentence.

    Scores: a one-piece word gets its log probability at a single [MASK]; a word of k ≤ 3
    word pieces gets the mean over its pieces at k masks (an over-estimate, so a long
    distractor is rejected rather than wrongly accepted); the answer gets the mean of its
    left-to-right pseudo-log-likelihood (one pass per piece, earlier pieces visible).
    Longer distractors are unscorable and rejected.

    Raw probabilities favour frequent words ("superintendent" beats "loudspeaker" in
    "she spoke through the ___"), so fit is also measured as p(word | gap) / p(word): the
    contextual probability over the word's corpus frequency (wordfreq). A distractor is
    *plausible* — rejected — if its fit reaches LM_RATIO of the answer's fit, its
    probability reaches LM_PROB_RATIO of the answer's (a rare answer has a huge fit, which
    would let common words that fit well pass), or its probability alone reaches LM_CEILING.

    The cache keeps, per sentence, the answer's probability and the verdicts on the
    distractors the question builder actually tried (in its order, until ACCEPT_LIMIT were
    accepted): "x" rejected, "ok" accepted. A distractor without a verdict for a sentence
    the model has judged counts as rejected, so a build without the model reproduces the
    cached questions exactly."""

    MAX_PIECES = 3

    def __init__(self, path: Path = CACHE_PATH, model_dir: Path | None = None):
        self.path = path
        data = json.loads(path.read_text("utf-8")) if path.exists() else {}
        if data.pop(RULE_KEY, None) != RULE:
            data = {}  # thresholds changed: the cached verdicts no longer apply
        self.data: dict[str, dict] = data
        self.model_dir = model_dir
        self.dirty = False
        self._model = None
        self._pieces: dict[str, list[int]] = {}
        self._used: dict[str, set[str]] = {}  # verdicts looked up by this build (see prune)

    @staticmethod
    def key(text: str, gap: Gap) -> str:
        return f"{text[:gap.start]}___{text[gap.end:]}"

    def get(self, key: str) -> dict | None:
        return self.data.get(key)

    def available(self) -> bool:
        return self.model_dir is not None and (self.model_dir / "config.json").exists()

    def verdict(self, key: str, form: str) -> bool | None:
        """True: a plausible fill (rejected); False: accepted; None: not judged."""
        entry = self.data.get(key)
        if entry is None:
            return None
        f = form.lower()
        self._used.setdefault(key, set()).add(f)
        return True if f in entry["x"] else False if f in entry["ok"] else None

    def _judged(self, key: str, form: str) -> bool:
        """Like ``verdict`` but not a lookup (see prune): a form judged once and never walked
        again is not needed by any question."""
        entry = self.data.get(key)
        return entry is not None and (form in entry["x"] or form in entry["ok"])

    def rejects(self, key: str, form: str) -> bool:
        """A sentence the model never judged is unchecked (allowed); in a judged one, only
        distractors judged implausible pass."""
        return key in self.data and self.verdict(key, form) is not False

    @staticmethod
    def plausible(lp_answer: float, prior_answer: float, lp: float, prior: float) -> bool:
        return (lp >= math.log(LM_CEILING) or lp >= lp_answer + math.log(LM_PROB_RATIO)
                or lp - prior >= lp_answer - prior_answer + math.log(LM_RATIO))

    def _load(self):
        if self._model is None:
            from transformers import AutoModelForMaskedLM, AutoTokenizer

            self._tok = AutoTokenizer.from_pretrained(self.model_dir)
            self._model = AutoModelForMaskedLM.from_pretrained(self.model_dir).eval()
        return self._tok, self._model

    def pieces(self, text: str) -> list[int]:
        if text not in self._pieces:
            self._pieces[text] = self._load()[0](text, add_special_tokens=False)["input_ids"]
        return self._pieces[text]

    def score(self, items: list[tuple[str, str, list[str]]], batch: int = 24,
              progress: Callable[[int, int], None] | None = None) -> list[tuple[float, dict[str, float | None]]]:
        """(masked sentence, answer, forms) -> (log p(answer), {form: log p or None if unscorable})."""
        import torch

        tok, model = self._load()
        cls, sep, mask, pad = tok.cls_token_id, tok.sep_token_id, tok.mask_token_id, tok.pad_token_id
        k_max = self.MAX_PIECES

        def rows_for(key: str, answer: str) -> list[tuple[list[int], list[int]]]:
            left, right = key.split("___", 1)
            lt, rt, at_ = self.pieces(left), self.pieces(right), self.pieces(answer.lower())
            rows = []  # (input ids, positions of the gap pieces)
            for k in range(1, k_max + 1):
                rows.append(([cls, *lt, *[mask] * k, *rt, sep], list(range(1 + len(lt), 1 + len(lt) + k))))
            for i in range(len(at_)):  # the answer, left to right: pieces before i visible
                rows.append(([cls, *lt, *at_[:i], *[mask] * (len(at_) - i), *rt, sep], [1 + len(lt) + i]))
            return rows

        out = []
        for i in range(0, len(items), batch):
            chunk = items[i:i + batch]
            all_rows = [rows_for(k, a) for k, a, _ in chunk]
            flat = [r for rows in all_rows for r in rows]
            width = max(len(ids) for ids, _ in flat)
            input_ids = torch.tensor([ids + [pad] * (width - len(ids)) for ids, _ in flat])
            where = [(ri, c) for ri, (_, cols) in enumerate(flat) for c in cols]
            at = {w: n for n, w in enumerate(where)}
            with torch.no_grad():  # the LM head runs only at the gap positions
                hidden = model.bert(input_ids=input_ids, attention_mask=(input_ids != pad).long()).last_hidden_state
                sel = hidden[torch.tensor([w[0] for w in where]), torch.tensor([w[1] for w in where])]
                logp = model.cls(sel).log_softmax(-1).numpy()
            r = 0
            for (key, answer, forms), rows in zip(chunk, all_rows):
                answer_ids = self.pieces(answer.lower())
                lp_answer = sum(float(logp[at[(r + k_max + j, rows[k_max + j][1][0])], t])
                                for j, t in enumerate(answer_ids)) / len(answer_ids)
                scores: dict[str, float | None] = {}
                for f in forms:
                    ids = self.pieces(f.lower())
                    k = len(ids)
                    scores[f] = (sum(float(logp[at[(r + k - 1, rows[k - 1][1][j])], ids[j]]) for j in range(k)) / k
                                 if 1 <= k <= k_max else None)
                out.append((lp_answer, scores))
                r += len(rows)
            if progress:
                progress(min(i + batch, len(items)), len(items))
        return out

    def fill(self, requests: list[tuple[str, str, list[str]]], zipf: Callable[[str], float] | None = None,
             progress: Callable[[int, int], None] | None = None) -> int:
        """Judge the forms without a verdict in (masked sentence, answer, forms) requests;
        returns how many sentences were scored."""
        todo = [(k, a, list(dict.fromkeys(f.lower() for f in forms if not self._judged(k, f.lower()))))
                for k, a, forms in requests]
        todo = [t for t in todo if t[2]]
        if not todo or not self.available():
            return 0
        if zipf is None:
            from wordfreq import zipf_frequency

            zipf = lambda w: zipf_frequency(w, "en")  # noqa: E731
        prior = lambda w: (max(zipf(w), 1.0) - 9) * math.log(10)  # noqa: E731
        for (key, answer, forms), (lp_answer, scores) in zip(todo, self.score(todo, progress=progress)):
            entry = self.data.setdefault(key, {"p": float(f"{math.exp(lp_answer):.3g}"), "x": [], "ok": []})
            for f in forms:
                bad = scores[f] is None or self.plausible(lp_answer, prior(answer.lower()), scores[f], prior(f))
                entry["x" if bad else "ok"].append(f)
            entry["x"].sort()
            entry["ok"].sort()
        self.dirty = True
        return len(todo)

    def judge(self, index: "GapIndex", entries: Iterable[Entry], zipf: Callable[[str], float] | None = None,
              progress: Callable[[int, int], None] | None = None, rounds: int = 12) -> None:
        """Let the model judge every distractor the question builder will try — round after round
        until nothing is left, so the next build asks for nothing and builds the same questions."""
        entries = list(entries)
        for _ in range(rounds):
            if not self.available() or not self.fill(index.lm_requests(entries), zipf, progress):
                return

    def prune(self) -> int:
        """After a full build: forget verdicts it never looked up — neither by the question builder
        nor by ``GapIndex.lm_requests`` (sentences of removed words, candidates that are no longer
        tried). The next build walks the same candidates, so the result does not change and the
        model has nothing to re-judge; the cache just stays small. Returns the number dropped."""
        dropped = 0
        for key in list(self.data):
            used, entry = self._used.get(key, set()), self.data[key]
            if not used:
                dropped += len(entry["x"]) + len(entry["ok"])
                del self.data[key]
                continue
            for field in ("x", "ok"):
                keep = [f for f in entry[field] if f in used]
                dropped += len(entry[field]) - len(keep)
                entry[field] = keep
        self.dirty |= dropped > 0
        return dropped

    def save(self) -> None:
        if self.dirty:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            dump = lambda v: json.dumps(v, ensure_ascii=False, separators=(",", ":"))  # noqa: E731
            lines = [f"{dump(k)}:{dump(v)}" for k, v in [(RULE_KEY, RULE), *sorted(self.data.items())]]
            self.path.write_text("{\n" + ",\n".join(lines) + "\n}\n", encoding="utf-8")  # a line per sentence
            self.dirty = False


def rejection_reason(target: Entry, cand: Entry, gap: Gap, similarity=None) -> str | None:
    if cand.id == target.id or cand.lemma.lower() == target.lemma.lower():
        return "same_word"
    if cand.pos != target.pos:
        return "pos_mismatch"
    if sensitive(cand.lemma, cand.pos):
        return "sensitive_word"
    if abs(level_index(cand.level) - level_index(target.level)) > 1:
        return "level_out_of_range"
    if not target.group or not cand.group:
        return "unknown_semantic_group"
    if cand.group == target.group or (cand.hard_group and cand.hard_group == target.hard_group):
        return "same_semantic_group"
    if cand.senses & target.senses:
        return "shared_sense"
    if cand.lemma.lower() in target.synonyms or target.lemma.lower() in cand.synonyms:
        return "synonym"
    if (cand.ru_terms | cand.ru_all) & (target.ru_terms | target.ru_all):
        return "shared_translation"
    if (cand.synset and cand.synset in target.ancestors) or (target.synset and target.synset in cand.ancestors):
        return "hypernym_relation"
    if " " in cand.lemma and " " not in target.lemma:
        return "multiword"
    if leaks(target.example or "", [cand.lemma, *cand.variants]):
        return "in_sentence"
    if similarity and similarity(target, cand) >= SIMILARITY_LIMIT:
        return "too_similar"
    return None


class GapIndex:
    def __init__(self, entries: Iterable[Entry], zipf: Callable[[str], float], lm: GapLM | None = None,
                 similarity=None):
        self.by_pos_level: dict[tuple[str, str], list[Entry]] = defaultdict(list)
        for e in entries:
            self.by_pos_level[(e.pos, e.level)].append(e)
        self.zipf = zipf
        self.lm = lm
        self.similarity = similarity
        self._tried: dict[str, tuple[list[tuple[Entry, str]], Iterator[tuple[Entry, str]]]] = {}

    def candidates(self, target: Entry) -> list[Entry]:
        from .models import LEVELS

        i = level_index(target.level)
        out: list[Entry] = []
        for lv in LEVELS[max(0, i - 1): i + 2]:
            out += self.by_pos_level.get((target.pos, lv), [])
        return out

    def _eligible(self, target: Entry, gap: Gap) -> Iterator[tuple[Entry, str]]:
        cands = stable_order(self.candidates(target), f"{target.id}|{TRAINER}")
        sentence = target.example.lower()
        for c in cands:
            if rejection_reason(target, c, gap, self.similarity):
                continue
            form = inflect(c, gap, self.zipf)
            if not form or form.lower() == gap.form.lower() or _pattern([form]).search(sentence):
                continue
            yield c, form

    def eligible(self, target: Entry, gap: Gap) -> Iterator[tuple[Entry, str]]:
        """Candidates in their gap form, in the question's (seeded) order, before the language
        model: computed lazily and memoised, as the model's requests walk them too."""
        seen, rest = self._tried.setdefault(target.id, ([], self._eligible(target, gap)))
        i = 0
        while True:
            if i == len(seen):
                nxt = next(rest, None)
                if nxt is None:
                    return
                seen.append(nxt)
            yield seen[i]
            i += 1

    def lm_requests(self, entries: Iterable[Entry]) -> list[tuple[str, str, list[str]]]:
        """(masked sentence, answer, forms) the model still has to judge: candidates in question
        order until ACCEPT_LIMIT are accepted (or MAX_TRIED are walked). Of the unjudged ones,
        the share accepted so far in this sentence is expected to pass (half in a new one)."""
        out = []
        for e in entries:
            if not (e.definitions and e.group and self.lm) or (gap := find_gap(e)) is None:
                continue
            key = GapLM.key(e.example, gap)
            pending: list[str] = []
            accepted = judged = 0
            for _, form in islice(self.eligible(e, gap), MAX_TRIED):
                v = self.lm.verdict(key, form)
                if v is None:
                    pending.append(form)
                else:
                    judged += 1
                    accepted += v is False
                if accepted + len(pending) * (accepted + 1) / (judged + 2) >= ACCEPT_LIMIT:
                    break
            if pending:
                out.append((key, gap.form, pending))
        return out

    def build_question(self, target: Entry) -> Question | None:
        gap = find_gap(target)
        if gap is None:
            return None
        qid = f"{target.id}:{TRAINER}:en"
        if not target.group:
            q = Question(qid, TRAINER, target.id, "en", [], "needs_review", ["unknown_semantic_group"])
            q.span, q.forms = gap.span, [gap.form]
            return q
        key = GapLM.key(target.example, gap)
        chosen: list[tuple[Entry, str]] = []
        for c, form in islice(self.eligible(target, gap), MAX_TRIED):
            if self.lm and self.lm.rejects(key, form):
                continue
            if any(form.lower() == f.lower() or c.senses & o.senses or c.group == o.group
                   for o, f in chosen):
                continue  # options must differ from each other too
            chosen.append((c, form))
            if len(chosen) >= POOL_SIZE:
                break
        status = "ok" if len(chosen) >= MIN_DISTRACTORS else "needs_review"
        q = Question(qid, TRAINER, target.id, "en", [c.id for c, _ in chosen], status,
                     [] if status == "ok" else ["insufficient_distractors"])
        q.span = gap.span
        q.forms = [gap.form, *(f for _, f in chosen)]  # aligned with [entry, *distractors]
        return q
