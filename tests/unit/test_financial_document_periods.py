import datetime as dt

from quant.data.financial_document_periods import document_periods


def parse(text, title='发行人最近三年的财务报告', issuer='金道科技'):
    return document_periods(title=title, issuer_name=issuer, published=dt.date(2026, 9, 10),
                            pages=[{'page': 2, 'text': text}, {'page': 3, 'text': text}])


def test_issuer_audit_scope_keeps_only_explicit_quarter_end_dates():
    result = parse('我们 审计了 浙江 金道科技股份有限公司财务报表，包括 2023 年12月31日资产负债表，'
                   '2023年度利润表。公司于2015年5月18日成立，2027年12月31日为计划日期。')
    assert result['periods'] == ['2023-12-31']
    assert result['evidence'][0]['page'] == 2


def test_statement_header_uses_period_range_and_comparative_balance_dates():
    result = parse('合并资产负债表 编制单位：浙江金道科技股份有限公司 '
                   '2026年6月30日 2025年12月31日 合并利润表 2026年1-6月')
    assert result['periods'] == ['2025-12-31', '2026-06-30']


def test_dates_in_footnotes_or_another_company_do_not_become_requests():
    assert parse('财务报表附注：金道科技2015年12月31日注册。')['periods'] == []
    assert parse('我们审计了收购标的公司财务报表，包括2025年12月31日资产负债表。')['periods'] == []
    assert parse('合并资产负债表 编制单位金道科技 2C25年12月31日')['periods'] == []


def test_balance_sheet_subsequent_events_is_not_a_statement_header():
    pages = [{'page': 2, 'text': '我们审计了金道科技2024年度财务报表'},
             {'page': 151, 'text': '截至2024年12月31日，本公司不存在重大或有事项。'
              '十三、资产负债表日后事项：拟按2025年3月31日总股本分红。'}]
    result = document_periods(title='发行人最近三年的财务报告', issuer_name='金道科技',
                              published=dt.date(2026, 9, 10), pages=pages)
    assert result['periods'] == ['2024-12-31']


def test_pro_forma_accounts_are_separate_even_when_issuer_and_dates_match():
    for title in ('金道科技备考合并财务报表审阅报告', '标的公司模拟合并财务报表审计报告'):
        result = parse('我们审计了金道科技2025年12月31日财务报表', title=title)
        assert result['periods'] == [] and result['excluded'] == 'pro_forma_or_simulated_accounts'


def test_st_prefix_is_removed_but_unknown_issuer_is_not_guessed():
    text = '合并资产负债表 编制单位：金道科技股份有限公司 2025年12月31日'
    assert parse(text, issuer='*ST金道科技')['periods'] == ['2025-12-31']
    assert parse(text, issuer='')['reason'] == 'issuer_name_not_available'


def test_stamped_statement_inherits_verified_document_issuer_but_conflicting_company_does_not():
    pages = [{'page': 2, 'text': '我们审计了金道科技股份有限公司2025年度财务报表'},
             {'page': 90, 'text': '合并资产负债表 2026年6月30日 编制单位（印章遮挡）'},
             {'page': 91, 'text': '合并利润表 2026年1一6月'},
             {'page': 92, 'text': '合并资产负债表 编制单位：另一家股份有限公司 2026年3月31日'}]
    result = document_periods(title='发行人最近一年一期财务报告', issuer_name='金道科技',
                              published=dt.date(2026, 9, 10), pages=pages)
    assert result['periods'] == ['2025-12-31', '2026-06-30']
    assert result['evidence'][1]['issuer_basis'] == 'issuer_title_and_document_audit'
    assert result['evidence'][1]['issuer_context_pages'] == [2]


def test_stock_abbreviation_does_not_replace_exact_registered_full_name():
    args = dict(title='北京百华悦邦科技股份有限公司最近一年一期财务报告', issuer_name='百邦科技',
                published=dt.date(2026, 9, 10), pages=[{'page': 1, 'text':
                '我们审计了北京百华悦邦科技股份有限公司2025年度财务报表'}])
    assert document_periods(**args)['periods'] == []
    assert document_periods(**args, issuer_full_name='北京百华悦邦科技股份有限公司')['periods'] == ['2025-12-31']


def test_column_order_does_not_hide_a_separate_statement_heading():
    pages = [{'page': 1, 'text': '我们审计了紫光股份有限公司2025年度财务报表'},
             {'page': 168, 'text': '母公司利润表\n2026年1-6月'},
             {'page': 169, 'text': '资产项目\n'*30+'母公司资产负债表\n2026年6月30日\n期末数'}]
    result = document_periods(title='紫光股份有限公司最近一年一期财务报告', issuer_name='紫光股份',
                              published=dt.date(2026, 9, 10), pages=pages)
    assert result['periods'] == ['2025-12-31', '2026-06-30']


def test_single_ocr_year_cannot_add_an_uncorroborated_period():
    pages = [{'page': 1, 'text': '我们审计了金道科技2024年度财务报表'},
             {'page': 111, 'text': '母公司现金流量表\n2021年度'}]
    result = document_periods(title='发行人最近三年财务报告', issuer_name='金道科技',
                              published=dt.date(2026, 9, 10), pages=pages)
    assert result['periods'] == ['2024-12-31']
    assert result['unconfirmed_evidence'][0]['period'] == '2021-12-31'
