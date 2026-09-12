import json
from quant.research.report_text_batch import summarize_requests


def test_counts_latest_results_but_charges_all_attempts_and_retains_pending():
    def row(key,state,second,cost):
        return {'cache_key':key,'state':state,'charged_usd':cost,'error':None,
            'created_at':f'2026-09-12T00:00:{second:02d}+00:00',
            'scores_json':json.dumps({'operating_improvement':{'score':0,'status':'scored'}}),
            'usage_json':json.dumps({'prompt_tokens':10,'completion_tokens':20})}
    attempts=[row('a','retryable',0,.01),row('a','success',5,.02),row('b','unknown',10,.03),row('other','success',15,.04)]
    result=summarize_requests(attempts,allowed_keys={'a','b','c'})
    assert result['successful_texts']==1 and result['unrequested_texts']==1
    assert result['batch_charged_or_reserved_usd']==.06
    assert result['shared_charged_or_reserved_usd']==.1
    assert result['success_fraction_terminal']==1.
    assert result['median_request_start_gap_seconds']==5.
    assert not result['selected_all_terminal']
    result=summarize_requests([row('a','retryable',0,.01)],allowed_keys={'a'})
    assert result['selected_all_terminal'] and result['success_fraction_terminal']==0.
