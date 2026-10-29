"""Explicit file-backed full-chain regressions; pure contract kernels stay fast."""

# Audited against the actual upstream builders and streamed timings.
# No test function or assertion is removed; default pytest still runs these.
FULL_CHAIN_CASES = {
    'test_m3_a_share_market_facts.py': {
        'test_bar_never_overrides_partial_open_suspension',
        'test_full_day_is_blocked_even_without_bar_or_limit',
        'test_market_facts_and_open_state_do_not_write_files',
        'test_market_facts_builder_binds_exact_eight_release_files',
        'test_market_facts_rejects_development_identity_mix',
        'test_non_full_day_missing_or_one_sided_limit_fails_closed',
        'test_open_state_does_not_read_close_high_low_volume',
        'test_open_state_schema_columns_order_and_duplicate_symbol_rejection',
        'test_partial_suspension_uses_exact_delimiter_and_half_open_0930',
    },
    'test_m3_a_share_reporting.py': {
        'test_build_is_deterministic_and_no_clobber',
        'test_public_contracts_and_three_scenario_tree_are_exact',
        'test_scenario_metrics_match_frozen_formulas_and_510300_benchmark',
        'test_scenarios_are_independent_fixed_order_and_share_market_facts',
        'test_verifier_rejects_identity_or_order_rule_mix',
        'test_verifier_rejects_missing_or_tampered_any_declared_file',
    },
    'test_m3_a_share_simulator.py': {
        'test_full_day_held_position_keeps_mark_and_unexplained_missing_bar_fails_closed',
        'test_result_is_invariant_to_input_row_order',
        'test_sell_proceeds_are_available_to_same_day_buys_and_terminal_not_forced',
        'test_session_order_captures_record_close_then_recognizes_and_settles_ex_date',
        'test_simulator_outputs_exact_seven_tables_and_decimal_invariants',
        'test_simulator_rejects_wrong_types_non_decimal_and_identity_mix',
    },
    'test_m3_alignment.py': {
        'test_alignment_closed_loop_one_to_one_cutoff_and_loaders',
        'test_alignment_manifest_or_receipt_bytes_are_bound',
        'test_alignment_no_clobber_and_rejects_formal_development_mix',
        'test_alignment_receipt_requires_exact_direct_closure',
        'test_alignment_rejects_work_horizon_schema_or_identity_drift_without_writes',
        'test_alignment_verifier_rejects_output_bytes_drift',
        'test_formal_alignment_verify_load_and_label_free_inference',
        'test_formal_builder_rejects_development_capabilities_before_write',
        'test_inference_is_label_free_and_keeps_scorable_rows_without_future_exit',
    },
    'test_m3_backtest_plan_artifact.py': {
        'test_cost_schedule_is_contiguous_canonical_and_scales_only_friction',
        'test_plan_fails_closed_for_missing_tail_next_session_or_non_signal_batch',
        'test_plan_maps_each_complete_signal_batch_to_strict_next_sh_session',
        'test_plan_no_clobber_and_rejects_development_identity_mix',
        'test_plan_receipt_exact_closure_and_output_tree',
        'test_plan_rejects_mixed_identity_or_non_a_share_without_writes',
        'test_plan_verifier_rejects_each_output_or_receipt_tamper',
    },
    'test_m3_evaluation_artifact.py': {
        'test_evaluation_bundle_closes_full_fold_dates_counts_metrics_and_receipt',
        'test_evaluation_identity_no_clobber_output_receipt_and_json_tamper',
        'test_wholesale_evaluation_bundle_from_other_work_is_rejected',
    },
    'test_m3_feature_artifact.py': {
        'test_artifact_verifier_rejects_request_response_schema_or_uri_drift',
        'test_development_feature_artifact_preserves_fold_shared_nan_contract',
        'test_feature_no_clobber_and_rejects_cross_kind_or_spec_drift',
        'test_feature_receipt_binds_all_declared_output_bytes',
        'test_feature_receipt_requires_exact_input_and_output_closure',
        'test_feature_verifier_rejects_echo_bytes_and_coverage_drift',
    },
    'test_m3_fold_plan_artifact.py': {
        'test_development_fold_plan_closed_loop_and_embargo_selection',
        'test_fold_plan_nominal_spec_json_and_receipt_fail_closed',
        'test_fold_plan_rejects_weak_upstream_receipts_and_supports_explicit_roots',
        'test_rebuild_and_reader_reject_non_session_boundary_and_strict_json',
    },
    'test_m3_formal_research_summary_artifact.py': {
        'test_formal_summary_closed_loop_exact_folds_math_projection_and_receipt',
    },
    'test_m3_model_artifact.py': {
        'test_model_build_uses_only_validation_l2_and_preserves_nan',
        'test_model_closed_loop_receipt_and_prediction_uses_best_iteration',
        'test_model_no_clobber_and_cross_work_or_horizon_rejected',
        'test_model_receipt_requires_exact_direct_closure',
        'test_model_verifier_rejects_any_output_tamper',
    },
    'test_m3_prediction_artifact.py': {
        'test_prediction_closed_loop_is_full_test_and_label_independent',
        'test_prediction_manifest_is_canonical_and_receipt_exact',
        'test_prediction_rejects_lineage_mix_and_no_clobber',
        'test_prediction_verifier_rejects_every_output_and_receipt_tamper',
        'test_wholesale_prediction_bundle_from_other_work_is_rejected',
    },
    'test_m3_target_artifact.py': {
        'test_r2_development_target_reuses_fixed_decimal_allocation_helper',
        'test_target_builder_rejects_prediction_key_drift_without_writes',
        'test_target_closed_loop_has_exact_domain_daily_counts_and_decimal_weights',
        'test_target_receipt_has_exact_thirteen_inputs_and_three_outputs',
        'test_target_rejects_identity_mix_low_coverage_empty_prediction_and_no_clobber',
        'test_target_spec_is_config_projection_not_caller_hashes',
        'test_target_verifier_rejects_output_or_receipt_tamper',
        'test_target_wholesale_bundle_from_foreign_work_is_rejected',
    },
}

# G1 end-to-end builds retain the real 300-symbol builder; constructor cases use fixed synthetic tables.
FULL_CHAIN_CASES.update({
    'test_m3_g1_candidate.py': {
        'test_calendar_list_date_change_changes_primary_key',
        'test_full_day_suspension_allows_factor_without_daily_bar',
        'test_happy_path_build_verify_audit',
        'test_price_change_changes_primary_key',
        'test_response_order_and_frame_row_order_stable_identity',
    },
    'test_m3_g1_candidate_actions.py': {
        'test_no_file_or_network_io_during_build',
        'test_p0d_audit_rejects_restored_out_of_scope_factors',
        'test_p0d_build_excludes_pre_first_bar_factor_jump',
        'test_p0d_r1_adv3a_out_of_scope_factor_still_rejected',
        'test_p0d_r1_audit_rejects_deleted_transition_evidence',
        'test_p0d_r1_happy_and_no_event_jump_still_pass',
        'test_p0d_r1_single_scoped_factor_allows_empty_evidence',
        'test_p0k_a_cninfo_ca_raw_changes_identity_without_ledger',
        'test_p0kc_candidate_build_audit_and_formal_receipt_closure',
        'test_wholesale_candidate_replacement_fails_verify',
    },
})
