"""Known Kiwi blind spots.

Some mistakes never show up as disagreement between Kiwi's candidates --
Kiwi is confidently wrong in all of them. Each rule here spots the
pattern, adds the reading Kiwi never proposes, and forces the span to Jev.
Add a rule whenever you find a repeated mistake in real content.
"""
from kiwi_ankimorphs.kimchi_merge import _KIMCHI_WORDS
from kiwi_ankimorphs.tokenizer import Token

from .candidates import Analysis, Option, Region
from .learner import Unit, base_tag, coarse


def _flat_best(analysis: Analysis) -> list[Unit]:
    units: list[Unit] = []
    for seg in analysis.segments:
        units.extend(seg.best.units if isinstance(seg, Region) else seg)
    return units


def force_region(analysis: Analysis, start: int, end: int,
                 extra: list[Option], note: str) -> None:
    """Replace every segment overlapping [start, end) with one forced Region
    whose options are Kiwi's best reading of that span plus `extra`."""
    before, inside, after = [], [], []
    for seg in analysis.segments:
        s, e = ((seg.start, seg.end) if isinstance(seg, Region)
                else (seg[0].start, seg[-1].end))
        (before if e <= start else after if s >= end else inside).append(seg)
    if any(isinstance(s, Region) and s.forced for s in inside):
        return  # already claimed by another rule
    kiwi_units: list[Unit] = []
    for seg in inside:
        kiwi_units.extend(seg.best.units if isinstance(seg, Region) else seg)
    lo = min(start, kiwi_units[0].start)
    hi = max(end, kiwi_units[-1].end)
    region = Region(lo, hi, [Option(tuple(kiwi_units), prob=1.0)] + extra,
                    forced=True, note=note)
    analysis.segments = before + [region] + after


def rule_bogo_particle(analysis: Analysis) -> None:
    """N+보고 ("친구보고 가라고 했어요" = said *to* my friend). Kiwi always
    reads it as 보다 (see) + -고 (FINDINGS.md #246)."""
    units = _flat_best(analysis)
    for n, bo, go in zip(units, units[1:], units[2:]):
        if (coarse(n.tag) in ("NOM", "PROPN") and base_tag(n.tag) != "MAG"
                and n.end == bo.start and bo.lemma == "보다"
                and base_tag(bo.tag) == "VV" and go.tokens[0].lemma == "고"
                and bo.end == go.start):
            tok = Token("보고", "JKB", bo.start, go.end - bo.start)
            particle = Unit("보고", "JKB", bo.start, go.end, (tok,))
            force_region(
                analysis, n.start, go.end,
                [Option((n, particle), source="rule:bogo")],
                note="보고 right after a person noun can be a colloquial "
                     "particle meaning 'to (someone)', like 한테/더러.")


# Pro-form stems whose fused forms (이렇게, 그런, 그러면, 아니면, 그래...) are
# dictionary headwords with the same meaning as their parts.
_PROFORM_STEMS = {"이렇다", "그렇다", "저렇다", "이러다", "그러다", "저러다",
                  "어떻다", "어쩌다", "아니다"}
_DEMONSTRATIVES = {"이", "그", "저"}


def _settle(seg: Region, winner: Option, source: str) -> None:
    for o in seg.options:
        o.prob = 0.0
    winner.prob, winner.source = 1.0, source


def rule_proform_policy(analysis: Analysis) -> None:
    """Policy, not ambiguity: 그렇게 vs 그렇다+-게, 그때 vs 그+때, 아니면 vs
    아니다+-면 mean the same thing either way, so don't ask Jev -- follow
    Kimchi Reader's headwords, since that's where the known-word list comes
    from: fused form if Kimchi lists it (그런, 그러면, 그때, 그래), otherwise
    the stem (이렇게 -> 이렇다, 아니면 -> 아니다). Settles without Jev.
    Deliberately narrow: 한데 ('outdoors') vs 하+-ㄴ데 is a real ambiguity
    and is still asked."""
    for seg in analysis.segments:
        if not isinstance(seg, Region) or seg.forced:
            continue
        singles = [o for o in seg.options if len(o.units) == 1]
        decomps = [o for o in seg.options if len(o.units) > 1 and (
            o.units[0].lemma in _PROFORM_STEMS
            or (o.units[0].lemma in _DEMONSTRATIVES
                and base_tag(o.units[0].tag) == "MM"))]
        if not singles or not decomps or len(singles) + len(decomps) != len(seg.options):
            continue
        single = max(singles, key=lambda o: o.prob)
        if single.units[0].lemma in _KIMCHI_WORDS:
            _settle(seg, single, "rule:kimchi_headword")
        else:
            _settle(seg, max(decomps, key=lambda o: o.prob), "rule:kimchi_headword")


RULES = [rule_bogo_particle, rule_proform_policy]


def apply_rules(analysis: Analysis) -> Analysis:
    for rule in RULES:
        rule(analysis)
    return analysis
