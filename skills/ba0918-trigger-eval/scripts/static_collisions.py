#!/usr/bin/env python3
"""
trigger-eval: Static collision pre-pass.

Ranks description pairs by lexical Jaccard similarity. Pure functions, no LLM.
Used ONLY for defining "adjacent" skills for hard-negative case generation.

Not a predictor of measured confusion: in the 2026-07-27 run (188 cases) the
top 3 pairs by this ranking had zero confusion while the only confused pair
ranked 7th. Confusion comes from missing discriminating information,
which vocabulary set operations cannot see — so this ranking must not drive
revision priority or merge-candidate nomination. Hard-negative generation
survives because it needs pairs that *look* confusable, not pairs that
*are* confused.
"""

import argparse
import json
import re
import sys
from itertools import combinations
from pathlib import Path
from typing import Any

_ASCII_RE = re.compile(r"[a-z0-9]{2,}")
# Contiguous CJK runs: Hiragana, Katakana, CJK unified ideographs.
_CJK_RUN_RE = re.compile(r"[぀-ヿ一-鿿]+")

# English function words plus the words the trigger-phrase convention mandates.
# Measured over the 48 descriptions on 2026-07-27, the top of the frequency table was
# the 98% / when 98% / use 98% / or 96% / user 96% / says 92% / and 90% -- the boilerplate
# `Use when the user says ...` rides on nearly every description. A token present in almost
# every document adds to both the intersection and the union of every pair, so it inflates
# Jaccard without discriminating anything. Japanese descriptions never showed this because
# their particles do not survive tokenization as separate words, which is why the noise only
# appeared after the corpus went English.
#
# This is a **fixed list, deliberately not a document-frequency cutoff**. A DF filter would
# adapt to the corpus, but this script feeds a measurement instrument: adding one skill would
# shift the vocabulary and therefore every pair score, so two runs would stop being comparable.
# The list holds grammatical words and convention boilerplate only -- never a domain word.
# Content words that happen to be common (`check`, `plan`, `review`, `skill`) stay in.
_EN_STOPWORDS = frozenset(
    """
    an and any are as at be been but by can do does for from had has have if in into is it its
    no not of on one only or other over so than that the their them then there these they this
    those through to up was were what when where which while who why will with would you your
    say saying says use used user users uses
    """.split()
)


def tokenize(text: str) -> set[str]:
    """Lexical tokenization for similarity.

    - ASCII alphanumeric runs of length >= 2 (single letters dropped as noise),
      lowercased, with English stopwords removed (see `_EN_STOPWORDS`).
    - Japanese (CJK) text: each contiguous run is split into sliding bigrams
      so multi-character words overlap measurably. Bigrams are far more
      discriminating than single-character unigrams (which collide on common
      particles/kana). A length-1 run yields no token; a length-2 run yields
      exactly one bigram (e.g. "計画").

    Stopword removal applies to the ASCII path only. CJK bigrams are left alone: a bigram is a
    fragment of a word, not a word, so a word list cannot be matched against it without cutting
    into content.
    """
    lowered = text.lower()
    tokens = {t for t in _ASCII_RE.findall(lowered) if t not in _EN_STOPWORDS}
    for run in _CJK_RUN_RE.findall(lowered):
        for i in range(len(run) - 1):
            tokens.add(run[i : i + 2])
    return tokens


def jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity |a∩b| / |a∪b|. Empty ∪ empty := 0.0."""
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def pairwise_collisions(
    skills: list[dict[str, str]], top_n: int | None = None
) -> list[dict[str, Any]]:
    """Rank all skill pairs by description Jaccard similarity (descending).

    Each entry: {a, b, jaccard, shared: [sorted shared tokens]}.
    Ties are broken deterministically by (a, b) name order.
    """
    tokenized = [(s["name"], tokenize(s.get("description", ""))) for s in skills]
    pairs: list[dict[str, Any]] = []
    for (name_a, tok_a), (name_b, tok_b) in combinations(tokenized, 2):
        score = jaccard(tok_a, tok_b)
        pairs.append(
            {
                "a": name_a,
                "b": name_b,
                "jaccard": score,
                "shared": sorted(tok_a & tok_b),
            }
        )
    pairs.sort(key=lambda p: (-p["jaccard"], p["a"], p["b"]))
    if top_n is not None:
        pairs = pairs[:top_n]
    return pairs


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rank skill description pairs by lexical Jaccard similarity"
    )
    parser.add_argument(
        "input", type=str,
        help="collect_descriptions.py JSON output (file path, or '-' for stdin)",
    )
    parser.add_argument("--top-n", type=int, default=None, help="Limit to top N pairs")
    parser.add_argument("--output", type=str, default=None, help="Output file (default stdout)")
    args = parser.parse_args()

    if args.input == "-":
        data = json.load(sys.stdin)
    else:
        data = json.loads(Path(args.input).read_text(encoding="utf-8"))

    skills = data["skills"] if isinstance(data, dict) else data
    pairs = pairwise_collisions(skills, top_n=args.top_n)
    result = {"pair_count": len(pairs), "pairs": pairs}

    json_str = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(json_str + "\n", encoding="utf-8")
    else:
        print(json_str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
