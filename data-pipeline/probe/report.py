"""Side-by-side report: current (Argos+WMT19 ensemble) vs other engines → report.html + summary."""
import html, json, sys
from collections import Counter
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from lexi_pipeline.mt import _collapsed, _stem_repeats, normalize, parts, rejection  # noqa: E402

items = json.loads((HERE / "probe_set.json").read_text("utf-8"))
ENGINES = [(n, json.loads((HERE / f"{n}_result.json").read_text("utf-8")))
           for n in ("argos", "google") if (HERE / f"{n}_result.json").exists()]
verdict = json.loads((HERE / "verdict.json").read_text("utf-8")) if (HERE / "verdict.json").exists() else {}


def issues(ru, en):
    if not ru:
        return ["нет перевода"]
    out = [r] if (r := rejection(ru, en)) else []
    if parts(ru) < parts(en): out.append("потеряна часть")
    if _collapsed(ru, en): out.append("свёрнуто в слово")
    if _stem_repeats(ru, en): out.append("повтор корня")
    return out


stats, rows = Counter(), []
for i in items:
    cols = [("current", i["current"])] + [(n, normalize(r[i["key"]], sentence=i["pos"] == "example")
                                           if r.get(i["key"]) else None) for n, r in ENGINES]
    for n, ru in cols:
        stats[n] += not issues(ru, i["en"])
        stats[n + "=="] += (ru or "").lower().strip(". ") == i["current"].lower().strip(". ")
    cell = lambda ru: html.escape(ru or "—") + "".join(f' <span class=bad>{html.escape(x)}</span>' for x in issues(ru, i["en"]))
    rows.append(f"<tr><td>{i['level']}</td><td><b>{html.escape(i['lemma'])}</b><br><small>{i['kind']}"
                f"{' · ' + ', '.join(i['flags']) if i['flags'] else ''}</small></td><td>{html.escape(i['en'])}</td>"
                + "".join(f"<td>{cell(ru)}</td>" for _, ru in cols) + f"<td>{html.escape(verdict.get(i['key'], ''))}</td></tr>")
n = len(items)
summary = f"{n} текстов. Без замечаний автоматических проверок: " + ", ".join(
    f"{name} {stats[name]}" for name, _ in [("current", 0), *ENGINES]) + "; совпадает с текущим: " + ", ".join(
    f"{name} {stats[name + '==']}" for name, _ in ENGINES)
head = "".join(f"<th>{n}</th>" for n in ["сейчас", *[e for e, _ in ENGINES]])
page = f"""<!doctype html><meta charset=utf-8><title>texi — проба перевода</title>
<style>body{{font:14px system-ui;margin:20px}}table{{border-collapse:collapse}}td,th{{border:1px solid #ccc;padding:4px 6px;vertical-align:top}}
th{{background:#f3f3f3;position:sticky;top:0}}.bad{{color:#b00;font-size:12px}}small{{color:#777}}</style>
<h2>Проба перевода texi</h2><p>{summary}</p>
<table><tr><th>ур.</th><th>слово</th><th>English</th>{head}<th>оценка</th></tr>
{''.join(rows)}</table>"""
(HERE / "report.html").write_text(page, "utf-8")
print(summary)
