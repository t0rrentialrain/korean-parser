"""python -m kparse FILE.srt|FILE.txt [-o out.jsonl] [--dry-run] [--show N]

--dry-run   Kiwi + rules only: report how many spans would go to Jev.
--show N    print the first N Jev decisions (or would-be questions).
"""
import argparse
import dataclasses
import json
import re
import sys
from pathlib import Path

from .parser import Parser


def read_lines(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() != ".srt":
        return [l.strip() for l in text.splitlines() if l.strip()]
    lines = []
    for block in re.split(r"\n\s*\n", text.strip()):
        rows = block.strip().splitlines()
        if len(rows) >= 3:
            lines.append(" ".join(r.strip() for r in rows[2:]))
    return lines


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="kparse")
    ap.add_argument("file", type=Path)
    ap.add_argument("-o", "--out", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--accept", type=float, default=0.9)
    ap.add_argument("--show", type=int, default=0)
    args = ap.parse_args()

    lines = read_lines(args.file)
    jev = None
    if not args.dry_run:
        from .jev import Jev
        jev = Jev()
    parser = Parser(jev=jev, accept=args.accept)

    if args.dry_run:
        n_regions = n_ask = n_forced = 0
        shown = 0
        for line in lines:
            if not re.search(r"[가-힣]", line):
                continue
            a = parser.analyze(line)
            for r in a.regions:
                n_regions += 1
                if parser.needs_jev(r):
                    n_ask += 1
                    n_forced += r.forced
                    if shown < args.show:
                        shown += 1
                        print(f"\n{line}\n  「{line[r.start:r.end]}」"
                              + (" (rule)" if r.forced else ""))
                        for o in r.options:
                            print(f"    {o.prob:5.2f}  {o.describe()}")
        print(f"\n{len(lines)} lines, {n_regions} ambiguous spans, "
              f"{n_ask} would go to Jev ({n_forced} forced by rules)")
        return

    parsed = parser.parse_lines(lines)
    if args.out:
        with args.out.open("w", encoding="utf-8") as f:
            for p in parsed:
                f.write(json.dumps(dataclasses.asdict(p), ensure_ascii=False) + "\n")
    asked = [q for p in parsed for q in p.asked]
    for p in parsed:
        for q in p.asked[:max(0, args.show)]:
            print(f"\n{p.text}\n  「{q['target']}」 -> {q['answer']} ({q['confidence']:.2f})")
            for i, o in enumerate(q["options"]):
                print(f"    {'abcdefghijklmnopqrstuvwxyz'[i]}) {o}")
        args.show -= len(p.asked)
    review = sum(w.review for p in parsed for w in p.words)
    print(f"\n{len(parsed)} Korean lines, {len(asked)} Jev questions in "
          f"{jev.calls} calls, {jev.input_tokens} tokens (${jev.cost_usd:.4f}), "
          f"{review} words flagged for review")


if __name__ == "__main__":
    main()
