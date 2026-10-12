"""Find the spans of a sentence where Kiwi's candidate parses disagree.

Kiwi's analyze(top_n=N) gives N whole-sentence parses with log-prob scores.
Rather than ask anyone to pick a whole parse, we cut the sentence at every
character position that is a unit boundary in *all* candidates. Between two
such cuts, either every candidate has the same units (agreed) or they
don't (a Region with 2+ Options). Each region is then a small, focused
decision -- the shape of question Jev is good at.

Option probability = softmax over candidate scores, summed over the
candidates that produce that option. It's an approximation (only top_n
parses are seen) but a good enough "is Kiwi sure?" signal.
"""
import math
from dataclasses import dataclass, field

from .learner import Unit, to_tokens, to_units


@dataclass
class Option:
    units: tuple[Unit, ...]
    prob: float = 0.0
    source: str = "kiwi"   # "kiwi" or the name of the rule that added it

    @property
    def signature(self) -> tuple:
        return tuple(u.key for u in self.units)

    def describe(self) -> str:
        return " + ".join(u.describe() for u in self.units)


@dataclass
class Region:
    start: int
    end: int
    options: list[Option]
    forced: bool = False   # a rule says: always ask, regardless of Kiwi's confidence
    note: str = ""         # extra guidance for the question (from a rule)

    @property
    def best(self) -> Option:
        return max(self.options, key=lambda o: o.prob)


@dataclass
class Analysis:
    text: str
    # One entry per span, in order: either a settled tuple of units or a Region.
    segments: list = field(default_factory=list)

    @property
    def regions(self) -> list[Region]:
        return [s for s in self.segments if isinstance(s, Region)]


def _cuts(units: list[Unit], n: int) -> set[int]:
    cuts = {0, n}
    for u in units:
        cuts.add(u.start)
        cuts.add(u.end)
    # Contractions (했 = 하+었, 그건 = 그거+ㄴ) make units overlap; never cut
    # strictly inside a unit.
    for u in units:
        cuts -= set(range(u.start + 1, u.end))
    return cuts


def analyze(kiwi, text: str, top_n: int = 5, max_gap: float = 10.0) -> Analysis:
    raw = kiwi.analyze(text, top_n=top_n, compatible_jamo=True)
    best_score = raw[0][1]
    cands = [(to_units(to_tokens(toks)), score) for toks, score in raw
             if best_score - score <= max_gap]
    z = sum(math.exp(s - best_score) for _, s in cands)
    weights = [math.exp(s - best_score) / z for _, s in cands]

    n = len(text)
    common = set.intersection(*(_cuts(u, n) for u, _ in cands))
    cuts = sorted(common)

    out = Analysis(text)
    for a, b in zip(cuts, cuts[1:]):
        by_sig: dict[tuple, Option] = {}
        for (units, _), w in zip(cands, weights):
            inside = tuple(u for u in units if a <= u.start and u.end <= b)
            opt = Option(inside)
            by_sig.setdefault(opt.signature, opt).prob += w
        opts = sorted(by_sig.values(), key=lambda o: -o.prob)
        if not any(o.units for o in opts):
            continue  # whitespace
        if len(opts) == 1:
            out.segments.append(opts[0].units)
        else:
            out.segments.append(Region(a, b, opts))
    return out
