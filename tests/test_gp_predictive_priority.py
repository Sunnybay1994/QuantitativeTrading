"""Synthetic boundary checks for the preregistered pure selection helper."""
import itertools
from dataclasses import replace
from pathlib import Path

import pytest

from quant.research.gp_predictive_priority import (
    Candidate,
    GroupIC,
    MechanismManifest,
    MechanismTerminal,
    SelectionRules,
    assess_candidate,
    rank_candidates,
)

MANIFEST = MechanismManifest((
    MechanismTerminal("fin_a", "financial", "snapshot-1", "published before signal"),
    MechanismTerminal("fin_b", "financial", "snapshot-1", "published before signal"),
))
CONTROLS = ("control_a", "control_b")
RULES = SelectionRules(3, 48, 100, 0.8, 5, 20)


def candidate(expression="fin_a", means=(0.03, 0.04, 0.05), correlation=0.2):
    return Candidate(expression, tuple(GroupIC(i, mean, 48, 100, 0.8)
                                        for i, mean in enumerate(means)),
                     (("control_a", correlation), ("control_b", -0.1)))


def assess(row, **kwargs):
    return assess_candidate(row, manifest=MANIFEST, control_ids=CONTROLS, rules=RULES, **kwargs)


def rank(rows, rules=RULES):
    return rank_candidates(rows, manifest=MANIFEST, control_ids=CONTROLS, rules=rules)


def test_settings_come_from_registration_without_mutating_it():
    import copy
    import tomllib

    path = Path(__file__).parents[1] / "configs/research/gp_predictive_priority_v2.toml"
    config = tomllib.loads(path.read_text(encoding="utf-8"))
    before = copy.deepcopy(config)
    assert SelectionRules.from_config(config) == RULES
    assert config == before
    assert config["auto_trade"] is False
    assert config["maximum_batches"] == 1
    with pytest.raises(ValueError, match="registration"):
        SelectionRules.from_config({**config, "version": "old_objective"})
    with pytest.raises(ValueError, match="Missing"):
        SelectionRules.from_config({"version": "predictive_priority_v2"})


def test_manifest_missing_or_empty_refuses_selection_even_with_no_candidates():
    with pytest.raises(ValueError, match="manifest"):
        rank_candidates([], manifest=None, control_ids=CONTROLS, rules=RULES)
    with pytest.raises(ValueError, match="nonempty"):
        MechanismManifest(())


def test_manifest_hash_freezes_ids_versions_availability_and_mechanism():
    assert MANIFEST.sha256 == MechanismManifest(tuple(reversed(MANIFEST.terminals))).sha256
    for changes in ({"terminal_id": "fin_c"}, {"input_version": "snapshot-2"},
                    {"availability": "signal plus one session"},
                    {"mechanism": "industry_relative_reversal"}):
        changed = MechanismManifest((replace(MANIFEST.terminals[0], **changes),
                                     MANIFEST.terminals[1]))
        assert changed.sha256 != MANIFEST.sha256
    with pytest.raises(ValueError, match="unique"):
        MechanismManifest((MANIFEST.terminals[0], MANIFEST.terminals[0]))
    for changes in ({"terminal_id": "bad.id"}, {"input_version": ""},
                    {"availability": " "}, {"mechanism": "financial_family_guess"}):
        with pytest.raises(ValueError, match="Manifest requires"):
            MechanismManifest((replace(MANIFEST.terminals[0], **changes),))


def test_exact_coverage_boundaries_and_positive_direction_pass():
    result = assess(candidate())
    assert result.eligible and result.direction == 1 and result.primary == 0.03
    assert result.secondary == 0.2
    assert result.mechanism_terminals == ("fin_a",)


def test_negative_means_choose_negative_direction_and_worst_directional_group():
    result = assess(candidate(means=(-0.03, -0.05, -0.04)))
    assert result.eligible and result.direction == -1 and result.primary == 0.03


def test_equal_group_direction_is_not_weighted_by_valid_months():
    row = candidate(means=(-0.15, 0.1, 0.1))
    row = replace(row, groups=(replace(row.groups[0], valid_months=72), *row.groups[1:]))
    result = assess(row)
    assert result.direction == 1  # Month-weighted pooling would be negative.
    assert result.primary == -0.15 and not result.eligible


@pytest.mark.parametrize("means", [(0, 0, 0), (0.1, 0, 0.2), (0.1, -0.2, 0.1)])
def test_zero_or_opposite_group_ic_is_hard_rejected(means):
    result = assess(candidate(means=means))
    assert result.direction == 1  # The exact-zero equal-group mean chooses positive.
    assert "nonpositive_directional_group_ic" in result.reasons


@pytest.mark.parametrize(("changes", "reason"), [
    ({"valid_months": 47}, "insufficient_valid_months"),
    ({"valid_months": None}, "insufficient_valid_months"),
    ({"minimum_symbols": 99}, "insufficient_symbols"),
    ({"minimum_symbols": None}, "insufficient_symbols"),
    ({"minimum_paired_coverage": 0.799999}, "insufficient_paired_coverage"),
    ({"minimum_paired_coverage": None}, "insufficient_paired_coverage"),
    ({"minimum_paired_coverage": float("nan")}, "insufficient_paired_coverage"),
    ({"minimum_paired_coverage": 1.01}, "insufficient_paired_coverage"),
    ({"mean_ic": None}, "invalid_mean_ic"),
    ({"mean_ic": float("inf")}, "invalid_mean_ic"),
    ({"mean_ic": float("nan")}, "invalid_mean_ic"),
    ({"mean_ic": 1.01}, "invalid_mean_ic"),
])
def test_each_group_measurement_is_required(changes, reason):
    row = candidate()
    row = replace(row, groups=(replace(row.groups[0], **changes), *row.groups[1:]))
    result = assess(row)
    assert not result.eligible
    assert f"group_0:{reason}" in result.reasons


@pytest.mark.parametrize("groups", [(), (0, 1), (0, 1, 1), (0, 1, 3), (0, 1, 2, 3)])
def test_missing_duplicate_or_extra_groups_reject(groups):
    row = replace(candidate(), groups=tuple(GroupIC(i, 0.1, 48, 100, 0.8) for i in groups))
    result = assess(row)
    assert "incomplete_or_duplicate_groups" in result.reasons
    assert result.direction is None


@pytest.mark.parametrize("correlations", [(), (("control_a", 0.1),),
    (("control_a", 0.1), ("control_a", 0.2)),
    (("control_a", 0.1), ("unknown", 0.2)),
    (("control_a", 0.1), ("control_b", None)),
    (("control_a", 0.1), ("control_b", float("nan"))),
    (("control_a", 0.1), ("control_b", float("inf"))),
    (("control_a", 0.1), ("control_b", 1.01)),
])
def test_control_measurements_cannot_be_missing_or_imputed(correlations):
    result = assess(replace(candidate(), control_correlations=correlations))
    assert not result.eligible and result.secondary is None


def test_explicit_control_manifest_required_and_absolute_max_used():
    for ids in ((), ("control_a", "control_a"), ("",)):
        with pytest.raises(ValueError, match="control IDs"):
            rank_candidates([], manifest=MANIFEST, control_ids=ids, rules=RULES)
    result = assess(replace(candidate(), control_correlations=(("control_a", -0.9),
                                                              ("control_b", 0.2))))
    assert result.secondary == 0.9


@pytest.mark.parametrize("expression", ["fin_a_extra", "financial_family", "fin_a(other)",
                                         "other # fin_a"])
def test_mechanism_requires_exact_terminal_ast_reference(expression):
    assert "required_mechanism_not_referenced" in assess(candidate(expression)).reasons


@pytest.mark.parametrize("expression", ['"fin_a"', "obj.fin_a", "fin_a[0]", "fin_a +",
                                         "func(name=fin_a)", "__import__('os')"])
def test_unsupported_syntax_cannot_smuggle_a_mechanism_reference(expression):
    assert "invalid_expression" in assess(candidate(expression)).reasons


def test_node_count_and_depth_match_gp_calls_excluding_window_parameters():
    result = assess(candidate("ts_corr(ts_slope(ts_product(ts_slope(fin_a,20),5),20),other,60)"))
    assert result.eligible and result.node_count == 6 and result.depth == 4
    result = assess(candidate("-((fin_a) + (fin_b))"))
    assert result.node_count == 4 and result.depth == 2
    assert result.mechanism_terminals == ("fin_a", "fin_b")
    assert assess(candidate("rank(" * 5 + "fin_a" + ")" * 5)).eligible
    assert "expression_exceeds_max_depth" in assess(
        candidate("rank(" * 6 + "fin_a" + ")" * 6)).reasons


@pytest.mark.parametrize(("expression", "nodes", "depth"), [
    ("((fin_a > fin_b)*1.0)", 3, 1),
    ("where((fin_a)>0,fin_b,other)", 4, 1),
    ("where((((fin_a > fin_b)*1.0))>0,fin_b,other)", 6, 2),
    ("ind_neutralize(fin_a,industry_l1)", 2, 1),
    ("ts_quantile(fin_a,0.25,60)", 2, 1),
])
def test_export_sugar_and_fixed_parameters_do_not_inflate_gp_complexity(expression, nodes, depth):
    result = assess(candidate(expression))
    assert result.eligible and result.node_count == nodes and result.depth == depth
    assert "industry_l1" not in result.mechanism_terminals


def test_primary_outside_band_cannot_be_overridden_by_novelty():
    high = candidate("fin_a", means=(0.03,) * 3, correlation=0.99)
    low = candidate("fin_b", means=(0.0289999,) * 3, correlation=0.0)
    assert [row.expression for row in rank([low, high]).selected] == ["fin_a", "fin_b"]


def test_inclusive_decimal_boundary_then_secondary_not_primary():
    high = candidate("fin_a", means=(0.1,) * 3, correlation=0.8)
    boundary = candidate("fin_b", means=(0.099,) * 3, correlation=0.1)
    assert [row.expression for row in rank([high, boundary]).selected] == ["fin_b", "fin_a"]


def test_band_recomputed_after_every_winner_and_input_permutation_invariant():
    # A wins first over B by novelty. C was outside A's band, but then beats B.
    rows = [candidate("fin_a", means=(0.0300,) * 3, correlation=0.2),
            candidate("fin_b", means=(0.0292,) * 3, correlation=0.4),
            candidate("rank(fin_a)", means=(0.0284,) * 3, correlation=0.1)]
    for permutation in itertools.permutations(rows):
        assert [row.expression for row in rank(permutation).selected] == [
            "fin_a", "rank(fin_a)", "fin_b"]


def test_ties_use_node_count_then_lexical_order_and_respect_registered_limit():
    rows = [candidate("rank(fin_a)"), candidate("fin_b"), candidate("fin_a")]
    result = rank(rows, replace(RULES, maximum_candidates=2))
    assert [row.expression for row in result.selected] == ["fin_a", "fin_b"]
    assert [row.expression for row in result.eligible_not_selected] == ["rank(fin_a)"]
    assert result.rejected == () and result.manifest_sha256 == MANIFEST.sha256


def test_rejections_remain_visible_and_duplicate_expressions_fail_closed():
    result = rank([candidate("unrelated"), candidate("fin_b", means=(0, 0, 0)), candidate()])
    assert [row.expression for row in result.selected] == ["fin_a"]
    assert [row.expression for row in result.rejected] == ["fin_b", "unrelated"]
    with pytest.raises(ValueError, match="Duplicate"):
        rank([candidate(), candidate(correlation=0.9)])
