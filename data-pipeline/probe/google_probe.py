"""Google Translate (public web endpoint — the same NMT engine as the Cloud Translation API) on the probe set."""
import json, sys, time, urllib.parse, urllib.request
from pathlib import Path
HERE = Path(__file__).resolve().parent
URL = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=ru&dt=t"


def translate(text: str) -> str:
    req = urllib.request.Request(URL, data=urllib.parse.urlencode({"q": text}).encode(),
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.loads(r.read().decode("utf-8"))
    return "".join(seg[0] for seg in body[0] if seg and seg[0])


def main() -> None:
    items = json.loads((HERE / "probe_set.json").read_text("utf-8"))
    out_path = HERE / "google_result.json"
    done = json.loads(out_path.read_text("utf-8")) if out_path.exists() else {}
    todo = [i for i in items if i["key"] not in done]
    for k in range(0, len(todo), 20):
        chunk = todo[k:k + 20]
        lines = translate("\n".join(i["en"] for i in chunk)).split("\n")
        if len(lines) != len(chunk):  # merged or split lines: one by one
            lines = [translate(i["en"]) for i in chunk]
        done.update({i["key"]: ru.strip() for i, ru in zip(chunk, lines)})
        out_path.write_text(json.dumps(done, ensure_ascii=False, indent=1), "utf-8")
        time.sleep(1.5)
    print(len(done), "->", out_path)


if __name__ == "__main__":
    main()
