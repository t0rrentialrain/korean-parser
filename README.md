# korean-parser (kparse)

A learner-oriented Korean parser. Kiwi does the heavy lifting; Jev
(TypeSafe's multiple-choice "System One" model) settles only the spans
Kiwi isn't sure about. Same approach as Matt's Mandarin parser.

## How it works

1. **Candidates**: `kiwi.analyze(top_n=5)` gives 5 whole-sentence parses with scores.
2. **Learner units**: each parse is projected to learner words: compounds fused
   via kiwi-ankimorphs' Kimchi merge (공부+하다 → 공부하다), stems in citation
   form, particles/endings kept as their own units.
3. **Regions**: the sentence is cut wherever *all* candidates have a word
   boundary. Spans where the candidates still differ become Regions. Differences
   a learner doesn't care about are ignored: EF vs EC, noun vs name on the same
   word, and allomorphs like 을/를 and -ㄹ/-을.
4. **Rules** (`kparse/rules.py`):
   - `rule_bogo_particle` covers Kiwi's blind spot N+보고 = "to (someone)".
     It adds the missing reading and forces a Jev question.
   - `rule_proform_policy` settles 그렇게/그때/아니면-type spans without Jev,
     following Kimchi Reader's headwords so parses line up with your known-word list.
5. **Jev**: regions where Kiwi's best option is under 0.9 probability become
   Choice questions, all of a line's questions in one call, with the
   neighbouring subtitle lines as context. Each question is asked twice with
   the options reversed and the probabilities averaged, which cancels Jev's
   position bias. If Jev answers "none of these" or its confidence is below
   0.5, the word gets `review: true` and keeps Kiwi's best guess.
6. **Grammar**: kiwi-ankimorphs' Tier-3 templates (것 같다, ㄹ 수 있다...) run
   on the final morphs.

Answers are cached in `.cache/jev.sqlite`, so re-runs are free.

## Usage

```
python -m kparse ../deks_naengteobyu_12.srt --dry-run --show 20   # no API calls
python -m kparse ../deks_naengteobyu_12.srt -o ep12.jsonl --show 20
```

```python
from kparse import Parser
from kparse.jev import Jev
p = Parser(jev=Jev())
p.parse("친구보고 가라고 했어요").words
```

The key is read from `$TYPESAFE_API_KEY` or a `TYPESAFE_API_KEY=...` line in
`.env` (gitignored).

## Numbers (덱스의 냉터뷰 EP.11, 431 lines)

449 ambiguous spans; 46 go to Jev; about $0.0015 for the episode.

## Next

- A gold set of hand-checked regions, to measure Jev vs Kiwi-top-1 accuracy.
- English glosses in the options (needs a dictionary source); Jev is
  strongest in English.
- Route `review` words to Claude (the "none of the above → full LLM" path).
- More blind-spot rules as real content turns them up.
