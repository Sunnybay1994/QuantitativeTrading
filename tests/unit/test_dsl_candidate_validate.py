"""C2 DSL compile partition helpers."""
from quant.research.dsl_candidate_validate import (
    compile_expression,
    illegal_rate,
    legal_examples,
    partition_candidates,
)


def test_compile_accepts_simple_expression():
    compile_expression("adj_close / delay(adj_close, 1) - 1", ["adj_close"])


def test_partition_rejects_bad_and_keeps_good():
    payload = {
        "candidates": [
            {
                "expression": "adj_close / delay(adj_close, 1) - 1",
                "direction": 1,
                "rationale": "short-term reversal",
                "sources": ["weekly_gap"],
            },
            {
                "expression": "rank(not_a_real_op(adj_close))",
                "direction": 1,
                "rationale": "bad",
                "sources": ["weekly_gap"],
            },
        ]
    }
    raw, validated, rejected = partition_candidates(
        payload, fields=["adj_close"], existing_keys=set()
    )
    assert len(raw) == 2
    assert len(validated) == 1
    assert validated[0]["source"] == "llm_weekly"
    assert len(rejected) == 1
    assert illegal_rate(2, 1) == 0.5


def test_legal_examples_picks_short_exprs():
    rows = [
        {"id": "a", "expression": "adj_close", "direction": 1},
        {"id": "b", "expression": "adj_close / delay(adj_close, 5) - 1", "direction": -1},
    ]
    examples = legal_examples(rows, limit=2)
    assert examples[0]["id"] == "a"
