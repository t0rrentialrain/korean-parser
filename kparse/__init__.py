"""kparse - learner-oriented Korean parser.

Kiwi proposes several candidate analyses per sentence. Wherever the
candidates agree (or Kiwi itself is confident), its answer is accepted.
The leftover uncertain spans become small multiple-choice questions for
Jev (TypeSafe's System One model). See README.md.
"""
import sys
from pathlib import Path

# Reuse kiwi-ankimorphs' compound merging, Tier-3 grammar templates and
# Token type rather than forking them.
_KA = Path(__file__).resolve().parents[2] / "kiwi-ankimorphs"
if str(_KA) not in sys.path:
    sys.path.insert(0, str(_KA))

from .parser import Parser, ParsedLine, Word  # noqa: E402

__all__ = ["Parser", "ParsedLine", "Word"]
