"""Pick 250 machine translations for a side-by-side engine trial: 100 flagged + 150 random A1–A2."""
import collections, json, random, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lexi_pipeline.mt import _collapsed, _stem_repeats, parts  # noqa: E402

cache = json.loads((ROOT / 'data/mt_en_ru.json').read_text('utf-8'))
lx = json.loads((ROOT / 'out/lexicon.json').read_text('utf-8'))
LV = ['A1', 'A2', 'B1', 'B2', 'C1', 'C2']
where = {}
for e in lx:
    for d in e['definitions']:
        if d['lang'] == 'ru' and d['source'] == 'machine':
            where.setdefault(d['text'], []).append((e['level'], e['lemma']))
    if e.get('exampleRu'):
        where.setdefault(e['exampleRu'], []).append((e['level'], e['lemma']))
items = []
for k, ru in cache.items():
    pos, en = k.split('|', 1)
    if not ru or ru not in where:
        continue
    lvl = min((w[0] for w in where[ru]), key=LV.index)
    lemma = next(w[1] for w in where[ru] if w[0] == lvl)
    flags = []
    if _stem_repeats(ru, en): flags.append('stem_repeat')
    if parts(ru) < parts(en): flags.append('lost_part')
    if _collapsed(ru, en): flags.append('collapsed')
    r = len(ru) / max(1, len(en))
    if r < 0.75: flags.append('short')
    if r > 1.9: flags.append('long')
    if re.search(r'человек|лицо', ru) and re.search(r'женск|мужск|взросл', ru): flags.append('person_phrase')
    items.append(dict(key=k, pos=pos, en=en, current=ru, level=lvl, lemma=lemma,
                      kind='example' if pos == 'example' else 'definition', flags=flags))
shown = [i for i in items if i['level'] in ('A1', 'A2')]
print('cache', len(cache), 'used', len(items), 'A1-A2', len(shown), 'chars', sum(len(k.split('|', 1)[1]) for k in cache))
random.seed(7)
pick = [i for i in items if i['en'] in ('an adult female person', 'an adult male person')]
flagged = [i for i in shown if i['flags'] and i not in pick]
random.shuffle(flagged)
pick += flagged[:100 - len(pick)]
rest_def = [i for i in shown if i not in pick and i['kind'] == 'definition']
rest_ex = [i for i in shown if i not in pick and i['kind'] == 'example']
random.shuffle(rest_def); random.shuffle(rest_ex)
pick += rest_def[:100] + rest_ex[:50]
for g, i in enumerate(pick):
    i['group'] = 'flagged' if g < 100 else 'random'
print(len(pick), collections.Counter(i['group'] + ':' + i['kind'] for i in pick))
(ROOT / 'probe/probe_set.json').write_text(json.dumps(pick, ensure_ascii=False, indent=1), 'utf-8')
