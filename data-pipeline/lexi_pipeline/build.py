"""Build CEFR-graded content packs.

    python -m lexi_pipeline.build                       # WikDict (pre-processed Wiktionary)
    python -m lexi_pipeline.build --wiktionary-xml enwiktionary-latest-pages-articles.xml.bz2
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

from .adapt import Vocabulary, adapt_definitions, readability_report
from .cefr import build_entries, read_cefr_csv
from .extra import collect_extra, extra_entries
from .distractors import TRAINERS, DistractorIndex
from .gapfill import GapIndex, GapLM
from .models import LEVELS, QUALITY, Definition, Entry, allowed_langs, level_index
from .mt import MODEL_NAME, TranslationCache, available_backends, normalize, rejection
from .technical import FIELDS, build_tech_entries, calibrate, collect_candidates, pick_tech_sense
from .simple_wiktionary import SimpleWiktionary
from .templates import generate_en, generate_ru
from .text import leaks, load_frequency, rank_ru_terms, stem
from .wiktionary import WikDictSource, WiktionaryDumpSource, english_fallback, pick_sense

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 2
DECK_INFO = {
    "general": {"title": "Общая лексика",
                "description": "Слова CEFR-J и Octanove (A1–C2) и частотная лексика WordNet для B2–C2"},
    "tech": {"title": "Техническая лексика",
             "description": "ИТ, электротехника, физика, математика, химия и инженерия — для технических вузов"},
}
SOURCES = [
    {"name": "CEFR-J Vocabulary Profile 1.5", "url": "https://github.com/openlanguageprofiles/olp-en-cefrj",
     "license": "Free for research and commercial use with attribution (Tono Laboratory, TUFS)"},
    {"name": "Octanove Vocabulary Profile C1/C2 1.0", "url": "https://github.com/openlanguageprofiles/olp-en-cefrj",
     "license": "CC BY-SA 4.0"},
    {"name": "Princeton WordNet 3.0 (via NLTK)", "url": "https://wordnet.princeton.edu/", "license": "WordNet License"},
    {"name": "Simple English Wiktionary (via kaikki.org / wiktextract) — learner definitions and examples",
     "url": "https://simple.wiktionary.org/", "license": "CC BY-SA 4.0"},
    {"name": "Wiktionary via WikDict en-ru", "url": "https://www.wikdict.com/", "license": "CC BY-SA 3.0"},
    {"name": "FrequencyWords ru (OpenSubtitles 2018)", "url": "https://github.com/hermitdave/FrequencyWords",
     "license": "CC BY-SA 4.0"},
    {"name": "wordfreq (English word frequencies)", "url": "https://github.com/rspeer/wordfreq",
     "license": "CC BY-SA 4.0 (data), Apache 2.0 (code)"},
    {"name": f"Argos Translate en→ru ({MODEL_NAME}, OPUS data) — offline machine translation of definitions",
     "url": "https://github.com/argosopentech/argos-translate",
     "license": "MIT (Argos Translate, CTranslate2); model trained on OPUS corpora by Aleksey Kutashov"},
    {"name": "Facebook FAIR WMT19 en→ru (facebook/wmt19-en-ru) — second offline translation model",
     "url": "https://huggingface.co/facebook/wmt19-en-ru", "license": "Apache 2.0"},
    {"name": "Google BERT base uncased — masked language model checking «Вставьте слово» distractors (build time)",
     "url": "https://huggingface.co/google-bert/bert-base-uncased", "license": "Apache 2.0"},
    {"name": "LemmInflect (English inflections for gap-fill options)", "url": "https://github.com/bjascob/LemmInflect",
     "license": "MIT"},
]
LM_DIR = ROOT / "raw" / "bert-base-uncased"  # masked LM for gap-fill checks (build time only)
RU_MAX_LEVEL = "B1"  # ru definitions are stored up to B1 (B1 words can be distractors in A2)


def wiktionary_senses(e: Entry, wikt) -> list:
    for v in [e.lemma, *e.variants]:
        senses = wikt.senses(v, e.pos)
        if senses:
            return senses
    return []


def assign_translation(e: Entry, senses: list, ru_freq: dict[str, int] | None) -> None:
    """Translations of the Wiktionary sense that matches the entry's English definition."""
    en = e.best_definition("en")
    sense = pick_sense(senses, en.text if en else None)
    e.ru_all = {t for s in senses for t in s.ru_terms}
    if sense:
        e.ru_terms = set(sense.ru_terms)  # all translations: used to block ambiguous distractors
        e.translation = ", ".join(rank_ru_terms(sense.ru_terms, ru_freq)) or None


def enrich(entries: list[Entry], wnsrc, wikt, stats: Counter, ru_freq: dict[str, int] | None = None) -> None:
    def ru_lookup(word: str, pos: str) -> list[str]:
        sense = pick_sense(wikt.senses(word, pos), None)
        return rank_ru_terms(sense.ru_terms, ru_freq) if sense else []

    for e in entries:
        in_wn = wnsrc.enrich(e)
        stats["in_wordnet"] += in_wn
        senses = wiktionary_senses(e, wikt)
        assign_translation(e, senses, ru_freq)
        heads = [e.lemma, *e.variants]
        if e.best_definition("en") is None:
            fb = english_fallback(senses)
            if fb and not leaks(fb, heads):
                e.definitions.append(Definition(fb, "en", "wiktionary", QUALITY["wiktionary_gloss"]))
                stats["en_from_wiktionary"] += 1
        if e.best_definition("en") is None:
            gen = generate_en(e.lemma, e.pos, wnsrc.first_gloss, has_senses=in_wn)
            if gen:
                e.definitions.append(gen.definition)
                stats["en_generated"] += 1
                stats[f"rule:{gen.rule}"] += 1
                if not e.group and gen.base_ref is not None:
                    e.group = wnsrc.group_of(gen.base_ref)
                    e.hard_group = wnsrc.hard_group_of(gen.base_ref)
        if not e.translation:
            gen = generate_ru(e.lemma, e.pos, ru_lookup)
            if gen:
                e.translation = gen.definition.text  # «быстро» for "quickly" (from "quick")
                # the distractor rules compare translations through ru_terms
                e.ru_terms |= {t for t in e.translation.split(", ") if t}
                stats["translation_generated"] += 1


def enrich_tech(entries: list[Entry], wikt, ru_freq: dict[str, int] | None) -> None:
    """Russian for technical senses only when the Wiktionary sense clearly matches."""
    for e in entries:
        senses = wikt.senses(e.lemma, e.pos)
        e.ru_all = {t for s in senses for t in s.ru_terms}
        sense = pick_tech_sense(senses, e.best_definition("en").text, e.domain, e.lemma)
        if not sense:
            continue
        e.ru_terms = set(sense.ru_terms)
        e.translation = ", ".join(rank_ru_terms(sense.ru_terms, ru_freq)) or None


def needs_russian(e: Entry) -> bool:
    return level_index(e.level) <= level_index(RU_MAX_LEVEL)


def mt_input(e: Entry) -> str | None:
    """English text to translate: the learner definition *with* its headword (the shown
    version masks it as "___", which would only confuse a translation model)."""
    d = e.best_definition("en")
    if d is None:
        return None
    return e.mt_source if d.source == "simple" and e.mt_source else d.text


def translate_ru(entries: list[Entry], stats: Counter, cache: TranslationCache, backend=None,
                 progress=None) -> None:
    """Russian definition = the English definition, machine-translated (cached).

    A bare word translation ("dog" → «собака») would turn the trainer into a word-pair
    quiz; the translated *definition* keeps it about meaning. The short translation is
    kept separately (``Entry.translation``) and shown only after answering. Examples of
    A1–A2 words are translated too (shown under the English example)."""
    want = [(e, src) for e in entries if needs_russian(e) and (src := mt_input(e))]
    examples = [e for e in entries if "ru" in allowed_langs(e.level) and e.example]
    if backend:
        items = [(src, e.pos) for e, src in want] + [(e.example, "example") for e in examples]
        glossary = {(src, e.pos): sorted(e.ru_terms) for e, src in want}
        cache.translate_missing(items, backend, progress=progress, glossary=glossary)
    for e, src in want:
        if not cache.has(src, e.pos):
            stats["ru_not_in_cache"] += 1
            continue
        ru = cache.get(src, e.pos)
        ru = normalize(ru) if ru else None
        if ru and rejection(ru, src):  # cached under older, looser checks
            stats["ru_rejected_from_cache"] += 1
            ru = None
        if ru:
            e.definitions.append(Definition(ru, "ru", "machine", QUALITY["machine"]))
            stats["ru_machine"] += 1
            stats[f"ru_machine_from:{e.best_definition('en').source}"] += 1
        else:
            stats["ru_untranslated"] += 1
    for e in examples:
        ru = cache.get(e.example, "example")
        if ru and not rejection(ru, e.example):
            e.example_ru = ru
            stats["ru_examples"] += 1


def pick_synonyms(e: Entry, zipf, limit: int = 3) -> list[str]:
    """Common one-word synonyms of the entry's sense, shown after answering."""
    own = stem(e.lemma)
    out = []
    for w in sorted(e.synonyms, key=lambda w: (-zipf(w), w)):
        if " " in w or "-" in w or w.lower() == e.lemma.lower() or stem(w).startswith(own[:5]) or zipf(w) < 3.0:
            continue
        out.append(w)
        if len(out) >= limit:
            break
    return out


def similarity_for(wnsrc):
    def sim(a: Entry, b: Entry) -> float:
        if a.synset and b.synset and a.pos in ("noun", "verb"):
            return wnsrc.similarity(a.synset, b.synset)
        return 0.0
    return sim


def rank_for(wnsrc):
    """Hard-mode ordering: closest chosen senses first."""
    def rank(a: Entry, b: Entry) -> float:
        if a.synset and b.synset and a.pos in ("noun", "verb"):
            return wnsrc.fast_similarity(a.synset, b.synset)
        return 0.0
    return rank


def hard_similarity_for(wnsrc):
    """Max similarity between one word's sense and *any* frequent sense of the other,
    so an option never matches another meaning of the target (and vice versa)."""
    def sim(a: Entry, b: Entry) -> float:
        if not (a.synset and b.synset) or a.pos not in ("noun", "verb"):
            return 0.0
        best = wnsrc.fast_similarity(a.synset, b.synset)
        for other in b.top_senses:
            best = max(best, wnsrc.fast_similarity(a.synset, other))
        for other in a.top_senses:
            best = max(best, wnsrc.fast_similarity(other, b.synset))
        return best
    return sim


def default_zipf():
    from wordfreq import zipf_frequency

    return lambda w: zipf_frequency(w, "en")


def entry_for_pack(e: Entry, pack_level: str) -> dict:
    """Russian definitions ship only where they can be shown: A1–A2 questions,
    and B1 words that serve as distractors in A2 Russian questions. The short
    translation is shown after answering a Russian (A1–A2) question only."""
    data = e.to_json()
    best: dict[str, dict] = {}
    for d in data["definitions"]:  # sorted by quality: the first one per language is shown
        best.setdefault(d["lang"], d)
    data["definitions"] = [d for lang, d in best.items()
                           if lang == "en" or level_index(pack_level) <= level_index(RU_MAX_LEVEL)]
    if "ru" not in allowed_langs(pack_level):
        data.pop("translation", None)
        data.pop("exampleRu", None)
    return data


def gap_index(entries: list[Entry], wnsrc, zipf=None, lm: GapLM | None = None) -> GapIndex:
    return GapIndex([e for e in entries if e.definitions and e.group], zipf or default_zipf(), lm, similarity_for(wnsrc))


def build_questions(entries: list[Entry], wnsrc, zipf=None, lm: GapLM | None = None, progress=None,
                    gaps: GapIndex | None = None) -> list:
    """``gaps``: an index whose candidates the model has already judged (see ``build``)."""
    # Only words we can define and classify may ever appear as distractors.
    usable = [e for e in entries if e.definitions and e.group]
    index = DistractorIndex(usable, similarity_for(wnsrc), hard_similarity_for(wnsrc), rank_for(wnsrc))
    if gaps is None:
        gaps = gap_index(entries, wnsrc, zipf, lm)
        if lm:  # gap-fill: a masked language model rejects distractors that would also fit
            lm.judge(gaps, entries, zipf, progress)
    questions = []
    for e in entries:
        if e.definitions and (q := gaps.build_question(e)):  # optional trainer: example sentences
            questions.append(q)
        hard_by_lang: dict[str, list[str]] = {}
        for lang in allowed_langs(e.level):
            if lang == "ru" and e.best_definition("ru") is None:
                continue  # Russian is optional for A1–A2
            hard_by_lang[lang] = [c.id for c in index.hard_pool(e, lang)]
            for trainer in TRAINERS:
                q = index.build_question(e, trainer, lang)
                if q.status == "ok":
                    q.hard = hard_by_lang[lang]
                questions.append(q)
    return questions


def write_packs(deck: str, entries: list[Entry], questions: list, out: Path) -> list[dict]:
    """A pack holds only its own level's words; distractors may live in the ±1 packs,
    which the client loads alongside (each word ships exactly once per deck)."""
    by_id = {e.id: e for e in entries}
    ok = [q for q in questions if q.status == "ok"]
    used = {q.entry_id for q in ok} | {d for q in ok for d in [*q.distractors, *q.hard]}
    levels = []
    for level in LEVELS:
        qs = [q for q in ok if by_id[q.entry_id].level == level]
        own = [e for e in entries if e.level == level and e.id in used]
        pack = {"schemaVersion": SCHEMA_VERSION, "deck": deck, "level": level,
                "entries": [entry_for_pack(e, level) for e in own],
                "questions": [{"trainer": q.trainer, "entryId": q.entry_id, "lang": q.lang,
                               "distractors": q.distractors, **({"hard": q.hard} if q.hard else {}),
                               **({"span": q.span, "forms": q.forms} if q.span else {})} for q in qs]}
        body = json.dumps(pack, ensure_ascii=False, separators=(",", ":"))
        name = f"{level}.json" if deck == "general" else f"{deck}-{level}.json"
        (out / name).write_text(body, encoding="utf-8")
        info = {
            "level": level, "file": name, "words": len({q.entry_id for q in qs}), "bytes": len(body.encode()),
            "hash": hashlib.sha256(body.encode()).hexdigest()[:12],
            "questions": dict(Counter(f"{q.trainer}:{q.lang}" for q in qs)),
            "hard": dict(Counter(f"{q.trainer}:{q.lang}" for q in qs if q.hard)),
        }
        if deck == "tech":  # the client lets learners pick fields: counts per field
            info["fields"] = {
                f: {"questions": dict(Counter(f"{q.trainer}:{q.lang}" for q in fq)),
                    "hard": dict(Counter(f"{q.trainer}:{q.lang}" for q in fq if q.hard))}
                for f in sorted({by_id[q.entry_id].domain for q in qs if by_id[q.entry_id].domain})
                if (fq := [q for q in qs if by_id[q.entry_id].domain == f])}
        levels.append(info)
    return levels


def build(raw: Path, out: Path, review: Path, wiktionary_xml: Path | None = None, wnsrc=None,
          zipf=None, cache: TranslationCache | None = None, backend=None, translate: bool = True,
          progress=None, simple: SimpleWiktionary | None = None, lm: GapLM | None = None) -> dict:
    t0 = time.time()
    rows = read_cefr_csv(raw / "cefrj-vocabulary-profile-1.5.csv") + read_cefr_csv(
        raw / "octanove-vocabulary-profile-c1c2-1.0.csv")
    entries, skipped = build_entries(rows)
    if wnsrc is None:
        from .wordnet_source import WordNetSource
        wnsrc = WordNetSource()
    if wiktionary_xml:
        wanted = {v for e in entries for v in [e.lemma, *e.variants]}
        wikt = WiktionaryDumpSource(wiktionary_xml, wanted)
    else:
        wikt = WikDictSource(raw / "wikdict-en-ru.sqlite3")
    stats: Counter = Counter(entries=len(entries), skipped=len(skipped))
    freq_path = raw / "ru_50k.txt"
    ru_freq = load_frequency(freq_path) if freq_path.exists() else None
    enrich(entries, wnsrc, wikt, stats, ru_freq)
    t_enrich = time.time() - t0

    # ---- technical deck
    zipf = zipf or default_zipf()
    general_by_key = {(e.lemma.lower(), e.pos): e for e in entries}
    common = {k for k, e in general_by_key.items() if level_index(e.level) <= level_index("B1")}
    labelled = wikt.labelled() if hasattr(wikt, "labelled") else {}
    cands = collect_candidates(wnsrc.wn, zipf, labelled, common)
    thresholds = calibrate(entries, zipf)
    tech = build_tech_entries(cands, general_by_key, wnsrc, zipf, thresholds)
    enrich_tech(tech, wikt, ru_freq)
    stats["tech_candidates"] = len(cands)
    stats["tech_entries"] = len(tech)
    stats.update(Counter(f"tech_field:{e.domain}" for e in tech))
    stats.update(Counter(f"tech_level_source:{e.level_source}" for e in tech))

    # ---- general deck expansion: frequent words beyond the CEFR lists (B2–C2, estimated)
    known = {v.lower() for e in entries for v in [e.lemma, *e.variants]} | {
        h.strip().lower() for s in skipped for h in s["headword"].split("/")}
    extra = extra_entries(collect_extra(wnsrc.wn, zipf, known, exclude={c.lemma for c in cands}), thresholds,
                          {e.id for e in entries})
    enrich(extra, wnsrc, wikt, stats, ru_freq)
    entries = entries + extra
    stats["general_extra"] = len(extra)
    stats.update(Counter(f"general_extra_level:{e.level}" for e in extra))

    # ---- level-adaptive English definitions (Simple English Wiktionary for lower levels)
    vocab = Vocabulary.from_entries(entries, zipf, thresholds, getattr(wnsrc, "wn", None))
    stats.update({f"readability_wordnet:{k}": v for k, v in readability_report(entries + tech, vocab).items()})
    simple_path = raw / "simple-extract.jsonl.gz"
    if simple is None and simple_path.exists():
        wanted_words = {v.lower() for e in entries + tech for v in [e.lemma, *e.variants]}
        simple = SimpleWiktionary.load(simple_path, wanted_words)
    adapt_log: list = []
    if simple is not None:
        adapt_definitions(entries + tech, simple, wnsrc, vocab, stats, adapt_log)
    stats.update({f"readability:{k}": v for k, v in readability_report(entries + tech, vocab).items()})
    for e in entries:
        if e.sense_changed:  # the translation must follow the new sense ("stop" → «остановка»)
            translation = e.translation
            assign_translation(e, wiktionary_senses(e, wikt), ru_freq)
            stats["translation_repicked"] += e.translation != translation
    for e in entries + tech:
        e.see_also = pick_synonyms(e, zipf)

    # ---- Russian definitions (offline machine translation, cached in the repo)
    cache = cache or TranslationCache()
    if backend is None and translate:
        backend = available_backends()
    translate_ru(entries + tech, stats, cache, backend if translate else None, progress)
    backend = None  # free the MT models before the gap-fill language model loads
    gc.collect()

    lm = lm or GapLM(model_dir=LM_DIR if translate else None)

    out.mkdir(parents=True, exist_ok=True)
    review.mkdir(parents=True, exist_ok=True)
    questions: list = []
    by_id: dict[str, Entry] = {}
    deck_manifests = []
    decks = (("general", entries), ("tech", tech))
    # The model judges every deck before any question is built: both decks share some example
    # sentences, and a verdict added later must not change questions built earlier — otherwise
    # a build from the cache alone would differ from the one that ran the model.
    gap_indexes = {deck: gap_index(deck_entries, wnsrc, zipf, lm) for deck, deck_entries in decks}
    for deck, deck_entries in decks:
        lm.judge(gap_indexes[deck], deck_entries, zipf, progress)
        lm.save()
    for deck, deck_entries in decks:
        deck_questions = build_questions(deck_entries, wnsrc, zipf, lm, progress, gaps=gap_indexes[deck])
        questions += deck_questions
        by_id.update({e.id: e for e in deck_entries})
        levels = write_packs(deck, deck_entries, deck_questions, out)
        deck_manifests.append({"id": deck, **DECK_INFO[deck], "levels": levels})
        stats[f"{deck}:questions_ok"] = sum(q.status == "ok" for q in deck_questions)
        stats[f"{deck}:questions_hard"] = sum(bool(q.hard) for q in deck_questions)
        gap_ok = [q for q in deck_questions if q.trainer == "gap-fill" and q.status == "ok"]
        stats[f"{deck}:questions_gap_fill"] = len(gap_ok)
        stats[f"{deck}:questions_gap_fill_lm_unchecked"] = sum(  # built without the model's verdict
            lm.get(f"{(x := by_id[q.entry_id].example)[:q.span[0]]}___{x[q.span[1]:]}") is None for q in gap_ok)
    # what the model would still be asked for counts as used too; 0 after a build with the model
    stats["gap_lm_pending"] = sum(len(gap_indexes[deck].lm_requests(deck_entries)) for deck, deck_entries in decks)
    stats["gap_lm_pruned"] = lm.prune()  # verdicts no question needs any more
    lm.save()
    version = hashlib.sha256("".join(l["hash"] for d in deck_manifests for l in d["levels"]).encode()).hexdigest()[:12]
    manifest = {"schemaVersion": SCHEMA_VERSION, "version": version, "decks": deck_manifests,
                "fields": {k: v["title"] for k, v in FIELDS.items()}, "sources": SOURCES}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    entries = entries + tech

    needs_review = [{**q.to_json(), "lemma": by_id[q.entry_id].lemma, "level": by_id[q.entry_id].level,
                     "deck": by_id[q.entry_id].deck} for q in questions if q.status == "needs_review"]
    (review / "needs_review.json").write_text(json.dumps(needs_review, ensure_ascii=False, indent=1), encoding="utf-8")
    # Full lexicon (incl. words that are not shipped) for the database seed / editors.
    (review / "lexicon.json").write_text(json.dumps([{**e.to_json(), "deck": e.deck} for e in entries],
                                                    ensure_ascii=False), encoding="utf-8")
    (review / "skipped.json").write_text(json.dumps(skipped, ensure_ascii=False, indent=1), encoding="utf-8")
    (review / "adapt_log.json").write_text(json.dumps(adapt_log, ensure_ascii=False, indent=1), encoding="utf-8")
    stats.update({
        "questions_total": len(questions),
        "questions_ok": sum(q.status == "ok" for q in questions),
        "questions_needs_review": len(needs_review),
        "seconds": round(time.time() - t0, 1),
        "seconds_enrich": round(t_enrich, 1),
    })
    stats.update(Counter(f"source:{d.source}:{d.lang}" for e in entries for d in e.definitions))
    stats.update(Counter(f"review:{r}" for q in needs_review for r in q["reasons"]))
    report = {"version": version, "stats": dict(sorted(stats.items()))}
    (review / "build_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    if os.environ.get("PYTHONHASHSEED") != "0":
        # Set iteration order (and NLTK's order of related synsets) depends on the hash seed;
        # a fixed seed keeps two builds of the same data byte-identical.
        os.execvpe(sys.executable, [sys.executable, "-m", "lexi_pipeline.build", *sys.argv[1:]],
                   {**os.environ, "PYTHONHASHSEED": "0",
                    "PYTHONPATH": os.pathsep.join(filter(None, [str(ROOT), os.environ.get("PYTHONPATH")]))})
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=ROOT / "raw")
    ap.add_argument("--out", type=Path, default=ROOT.parent / "apps" / "web" / "public" / "packs")
    ap.add_argument("--review", type=Path, default=ROOT / "out")
    ap.add_argument("--wiktionary-xml", type=Path, default=None)
    ap.add_argument("--no-translate", action="store_true",
                    help="use only cached translations (data/mt_en_ru.json) and gap-fill verdicts "
                         "(data/gap_lm.json), never run the models")
    args = ap.parse_args()

    last = {"total": -1, "step": 0}

    def progress(done: int, total: int) -> None:
        """Every ~10 % of a phase (translation, gap-fill checks), whatever the batch size."""
        step = done * 10 // max(total, 1)
        if total != last["total"] or step < last["step"]:  # a new phase started
            last.update(total=total, step=0)
        if done == total or step > last["step"]:
            last["step"] = step
            print(f"progress {done}/{total}", flush=True)

    report = build(args.raw, args.out, args.review, args.wiktionary_xml, translate=not args.no_translate,
                   progress=progress)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
