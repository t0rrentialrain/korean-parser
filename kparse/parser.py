"""Top-level parser: Kiwi candidates -> rules -> Jev for what's left."""
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from kiwipiepy import Kiwi
from kiwi_ankimorphs.patterns import match_patterns

from .candidates import Analysis, Region, analyze
from .jev import JevError
from .learner import Unit, coarse
from .rules import apply_rules

PUNCT = ".,!?…~\"'"
choice = lambda u: (u.lemma, coarse(u.tag))   # how a reading is identified in corrections


def fix_key(text: str, start: int, end: int) -> str:
    """Corrections are keyed by the whole space-separated chunk plus the ambiguous piece
    ("동생보고|보고"), so fixing 동생보고 doesn't also change 보고 싶다."""
    lo = text.rfind(" ", 0, start) + 1
    hi = text.find(" ", end) % (len(text) + 1)
    return f"{text[lo:hi].strip(PUNCT)}|{text[start:end]}"

HANGUL = re.compile(r"[가-힣]")
LETTERS = "abcdefghijklmnopqrstuvwxyz"
_PROFORM_ROOTS = {"이렇", "그렇", "저렇", "어떻"}


@dataclass
class Word:
    surface: str
    lemma: str
    tag: str
    start: int
    end: int
    source: str = "kiwi"        # kiwi | jev | rule:<name>
    confidence: float = 1.0
    review: bool = False        # Jev said "none of these" or was unsure


@dataclass
class ParsedLine:
    text: str
    words: list[Word] = field(default_factory=list)
    grammar: list[dict] = field(default_factory=list)  # Tier-3 patterns: {name, s, e}
    asked: list[dict] = field(default_factory=list)    # Jev questions, for debugging


def _question(text: str, region: Region, order: list[int]) -> dict:
    """One Choice question; options appear in `order` and are lettered in
    that order (so letters never reveal Kiwi's ranking)."""
    target = text[region.start:region.end]
    criteria = {LETTERS[pos]: {"what": region.options[i].describe()}
                for pos, i in enumerate(order)}
    criteria["none"] = {"what": "None of these analyses is correct for this sentence"}
    instructions = {
        "task": "A parser for Korean learners is splitting this sentence into "
                "words (base/dictionary forms) plus particles and endings. "
                f"Which analysis of 「{target}」 is correct in this sentence?",
        "target": target,
    }
    if region.note:
        instructions["hint"] = region.note
    return {"type": "choice", "instructions": instructions, "criteria": criteria}


def _orders(region: Region) -> list[list[int]]:
    """Each region is asked twice in one call -- Kiwi's order and reversed --
    and the probabilities averaged, cancelling Jev's position bias."""
    n = min(len(region.options), 25)
    return [list(range(n)), list(range(n))[::-1]]


def _combine(answers: list[dict], orders: list[list[int]]) -> tuple[int | None, float]:
    """Average per-option probabilities across orderings.
    Returns (option index or None for 'none of these', averaged probability)."""
    probs: dict = {}
    for a, order in zip(answers, orders):
        for letter, p in a.get("probabilities", {}).items():
            key = "none" if letter == "none" else order[LETTERS.index(letter)]
            probs[key] = probs.get(key, 0.0) + p / len(answers)
    best = max(probs, key=probs.get)
    return (None if best == "none" else best), probs[best]


class Parser:
    def __init__(self, jev=None, accept: float = 0.9, review_below: float = 0.5,
                 top_n: int = 5, workers: int = 8):
        self.kiwi = Kiwi()
        self.jev = jev
        self.accept = accept            # Kiwi option prob needed to skip Jev
        self.review_below = review_below
        self.top_n = top_n
        self.workers = workers
        # Your fixes: region surface text -> chosen reading [(lemma, coarse class), ...].
        # Checked before Kiwi's confidence or Jev, so a fix applies everywhere that text appears.
        self.corrections: dict[str, list] = {}

    # -- stage 1: Kiwi + rules (no network) --------------------------------
    def analyze(self, text: str) -> Analysis:
        analysis = apply_rules(analyze(self.kiwi, text, top_n=self.top_n))
        for r in analysis.regions:
            want = self.corrections.get(fix_key(text, r.start, r.end))
            pick = next((o for o in r.options if want and [list(choice(u)) for u in o.units] == want), None)
            if pick:
                for o in r.options:
                    o.prob = 0.0
                pick.prob, pick.source, r.forced = 1.0, "you", False
        return analysis

    def needs_jev(self, region: Region) -> bool:
        return region.forced or region.best.prob < self.accept

    # -- stage 2: decide regions ------------------------------------------
    def _decide(self, text: str, analysis: Analysis, ctx: dict, use_jev: bool = True) -> ParsedLine:
        line = ParsedLine(text)
        pending = {f"r{i}": r for i, r in enumerate(analysis.regions)
                   if self.needs_jev(r)}
        answers = {}
        if pending and self.jev is not None and use_jev:
            state = {"sentence": text, **ctx}
            questions = {f"{k}_{j}": _question(text, r, order)
                         for k, r in pending.items()
                         for j, order in enumerate(_orders(r))}
            try:
                answers = self.jev.ask(state, questions)
            except JevError:
                answers = {}   # Jev unreachable: keep Kiwi's best guesses rather than failing the line

        chosen: list[tuple[Unit, str, float, bool]] = []
        for seg in analysis.segments:
            if not isinstance(seg, Region):
                chosen += [(u, "kiwi", 1.0, False) for u in seg]
                continue
            key = next((k for k, r in pending.items() if r is seg), None)
            opt, source, conf, review = seg.best, seg.best.source, seg.best.prob, False
            got = [answers[f"{key}_{j}"] for j in range(2)
                   if key and f"{key}_{j}" in answers]
            if got:
                idx, conf = _combine(got, _orders(seg))
                line.asked.append({"target": text[seg.start:seg.end],
                                   "options": [o.describe() for o in seg.options],
                                   "answer": "none" if idx is None else LETTERS[idx],
                                   "confidence": conf})
                if idx is None or conf < self.review_below:
                    review = True   # keep Kiwi's best, flag for a stronger model / you
                else:
                    opt = seg.options[idx]
                    source = "jev" if opt.source == "kiwi" else opt.source
            elif key:
                review = seg.forced or seg.best.prob < self.review_below
            chosen += [(u, source, conf, review) for u in opt.units]

        line.words = [Word(text[u.start:u.end], u.lemma, u.tag, u.start, u.end,
                           src, round(c, 3), rv) for u, src, c, rv in chosen]
        raw = [t for u, *_ in chosen for t in u.tokens]
        # 이렇게/그렇게 하다 is "do it like this", not causative -게 하다: drop
        # templates whose first morph is the ending of a pro-form stem.
        line.grammar = [{"name": m.name, "s": m.tokens[0].start,
                         "e": m.tokens[-1].start + m.tokens[-1].length}
                        for m in match_patterns(raw)
                        if not (m.start > 0 and raw[m.start - 1].lemma in _PROFORM_ROOTS)]
        return line

    def parse(self, text: str, prev: str = "", next_: str = "") -> ParsedLine:
        ctx = {k: v for k, v in (("previous_line", prev), ("next_line", next_)) if v}
        return self._decide(text, self.analyze(text), ctx)

    def parse_lines(self, lines: list[str], use_jev: bool = True) -> list[ParsedLine]:
        """Parse a transcript, giving Jev the neighbouring lines as context.
        Lines without Hangul (e.g. English subtitle lines) are skipped."""
        idx = [i for i, l in enumerate(lines) if HANGUL.search(l)]
        # Kiwi runs serially; only the network-bound Jev calls are threaded.
        analyses = {i: self.analyze(lines[i]) for i in idx}

        def one(i):
            ctx = {}
            if i > 0:
                ctx["previous_line"] = lines[i - 1]
            if i + 1 < len(lines):
                ctx["next_line"] = lines[i + 1]
            return self._decide(lines[i], analyses[i], ctx, use_jev)

        with ThreadPoolExecutor(self.workers) as pool:
            return list(pool.map(one, idx))
