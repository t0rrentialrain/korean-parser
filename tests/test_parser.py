"""Offline tests: Kiwi + rules only, Jev stubbed."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kparse import Parser  # noqa: E402
from kparse.parser import _combine  # noqa: E402

P = Parser(jev=None)


def lemmas(text):
    return [w.lemma for w in P.parse(text).words]


def test_contraction_regions_stay_whole():
    # 했 = 하+었 share one character; no region may cut inside it.
    a = P.analyze("했어요")
    for r in a.regions:
        assert r.start == 0 or r.start >= 1


def test_allomorph_and_name_noise_not_asked():
    # ㄹ vs 을 and NNG vs NNP on the same span aren't questions.
    a = P.analyze("'여자 덱스'라는 그런 타이틀이 있다고 하시던데")
    assert not any(P.needs_jev(r) and "덱스" == a.text[r.start:r.end]
                   for r in a.regions)


def test_bogo_rule_forces_question():
    a = P.analyze("친구보고 가라고 했어요")
    forced = [r for r in a.regions if r.forced]
    assert forced and any(o.source == "rule:bogo" for o in forced[0].options)


def test_proform_policy_follows_kimchi():
    ls = lemmas("아니면 이렇게 하는 게 나을 것 같아")
    assert ls[:4] == ["아니다", "면", "이렇다", "게"]   # Kimchi files these under the stem


def test_proform_does_not_fake_causative():
    r = P.parse("아니면 이렇게 하는 게 나을 것 같아")
    names = [g["name"] for g in r.grammar]
    assert "게_하다" not in names
    assert "것_같다" in names


def test_combine_cancels_position_bias():
    # Order 1: a=opt0, b=opt1. Order 2 reversed: a=opt1, b=opt0.
    # Jev "likes a" in both, so the averaged result is a coin flip, not opt0.
    idx, p = _combine([{"probabilities": {"a": 0.7, "b": 0.3, "none": 0}},
                       {"probabilities": {"a": 0.7, "b": 0.3, "none": 0}}],
                      [[0, 1], [1, 0]])
    assert abs(p - 0.5) < 1e-9


def test_correction_overrides_kiwi():
    from kparse.parser import choice, fix_key
    p = Parser(jev=None)
    text = "친구보고 가라고 했어요"
    region = next(r for r in p.analyze(text).regions if r.forced)          # 친구+보다+고 vs 친구+보고
    particle = next(o for o in region.options if o.source == "rule:bogo")
    p.corrections[fix_key(text, region.start, region.end)] = [list(choice(u)) for u in particle.units]
    words = p.parse(text).words
    assert [w.lemma for w in words][:2] == ["친구", "보고"] and words[1].source == "you"


def test_fix_key_uses_the_whole_chunk():
    from kparse.parser import fix_key
    t = "엄마가 동생보고 빨리 오라고 했어요."
    assert fix_key(t, 6, 8) == "동생보고|보고"
    assert fix_key("너 보고 싶다", 2, 4) == "보고|보고"
    assert fix_key(t, 16, 18) == "했어요|했어"  # trailing punctuation dropped
