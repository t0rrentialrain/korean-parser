"""Project raw Kiwi morphemes onto learner-level units.

A "unit" is what a learner would look up or track: lexicalized compounds
are fused (공부+하다 -> 공부하다, via kiwi-ankimorphs' kimchi_merge), stems
get their citation form (먹 -> 먹다), and particles/endings stay as their
own units because they're learnable grammar too.

Each unit also carries a *coarse* class. Candidate parses are compared on
(span, lemma, coarse) so that tag distinctions which don't change what a
learner learns (EF vs EC on 구나, MAG vs NNG on 진짜, VV vs VX on 하다)
don't count as disagreements.
"""
from dataclasses import dataclass

from kiwi_ankimorphs.kimchi_merge import try_merge
from kiwi_ankimorphs.tokenizer import Token

PRED_TAGS = {"VV", "VX", "VA", "VCP", "VCN", "XSV", "XSA"}

_COARSE = {
    **dict.fromkeys(["NNG", "NNB", "NR", "NP", "MAG", "MAJ", "MM", "IC"], "NOM"),
    # NNG vs NNP on the same span+lemma isn't a segmentation question;
    # whether something is a name is decided separately.
    "NNP": "NOM",
    **dict.fromkeys(PRED_TAGS, "PRED"),
    "XPN": "AFFIX", "XSN": "AFFIX", "XR": "AFFIX",
}

# Plain-English tag names, used when describing options to Jev.
TAG_NAMES = {
    "NNG": "noun", "NNP": "proper noun (name)", "NNB": "bound noun",
    "NR": "numeral", "NP": "pronoun", "VV": "verb", "VX": "auxiliary verb",
    "VA": "adjective", "VCP": "copula 이다", "VCN": "negative copula 아니다",
    "MM": "determiner", "MAG": "adverb", "MAJ": "conjunctive adverb",
    "IC": "interjection", "JKS": "subject particle", "JKC": "complement particle",
    "JKG": "possessive particle", "JKO": "object particle",
    "JKB": "adverbial particle", "JKV": "vocative particle",
    "JKQ": "quotative particle", "JX": "auxiliary particle (은/는, 도, 만, 요...)",
    "JC": "conjunctive particle", "EP": "pre-final ending (tense/honorific)",
    "EF": "sentence-final ending", "EC": "connective ending",
    "ETN": "nominalizing ending", "ETM": "modifier ending",
    "XPN": "prefix", "XSN": "noun suffix", "XSV": "verb-forming suffix",
    "XSA": "adjective-forming suffix", "XR": "root",
}


def base_tag(tag: str) -> str:
    return tag.split("-")[0]  # VA-I -> VA (irregular-stem marker)


def coarse(tag: str) -> str:
    t = base_tag(tag)
    if t in _COARSE:
        return _COARSE[t]
    if t.startswith("J"):
        return "PART"
    if t.startswith("E"):
        return "END"
    return "SYM"  # S*, W_*, UN, Z_*


# Allomorphs of one grammatical morpheme (을/를, 은/는, -(으)ㄹ, -(으)ㄴ...)
# compare equal; Kiwi's choice between them isn't a learner question.
# Kept per class: particle 는 = 은, but modifier-ending 는 (present) != ㄴ (past).
_ALLO = {
    "PART": {"를": "을", "는": "은", "가": "이", "와": "과", "로": "으로"},
    "END": {"ㄹ": "을", "ㄴ": "은", "면": "으면", "며": "으며", "니까": "으니까"},
}


def _canon(lemma: str, cls: str) -> str:
    return _ALLO.get(cls, {}).get(lemma, lemma)


def citation(lemma: str, tag: str) -> str:
    return lemma + "다" if base_tag(tag) in PRED_TAGS else lemma


@dataclass(frozen=True)
class Unit:
    lemma: str        # citation form
    tag: str          # Kiwi tag of the unit (merged tag for compounds)
    start: int
    end: int
    tokens: tuple[Token, ...]  # the raw Kiwi morphemes behind this unit

    @property
    def key(self) -> tuple:
        cls = coarse(self.tag)
        return (self.start, self.end, _canon(self.lemma, cls), cls)

    def describe(self) -> str:
        name = TAG_NAMES.get(base_tag(self.tag), base_tag(self.tag))
        dash = "-" if coarse(self.tag) in ("END",) else ""
        return f"{dash}{self.lemma} [{name}]"


def to_tokens(kiwi_tokens) -> list[Token]:
    return [Token(lemma=t.form, pos=t.tag, start=t.start, length=t.len)
            for t in kiwi_tokens]


def to_units(tokens: list[Token]) -> list[Unit]:
    units: list[Unit] = []
    i = 0
    while i < len(tokens):
        merged = try_merge(tokens, i)
        if merged is not None:
            m, n = merged
            units.append(Unit(m.lemma, m.pos, m.start, m.start + m.length,
                              tuple(tokens[i:i + n])))
            i += n
            continue
        t = tokens[i]
        units.append(Unit(citation(t.lemma, t.pos), t.pos, t.start,
                          t.start + t.length, (t,)))
        i += 1
    return units
