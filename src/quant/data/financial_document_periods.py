"""Identify dated issuer statements in OCR text, excluding pro-forma accounts."""
import datetime as dt
import re
import unicodedata


def normalized(text: str) -> str:
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text))


def document_periods(*, title: str, issuer_name: str, published: dt.date, pages: list[dict],
                     issuer_full_name: str | None = None) -> dict:
    title = normalized(title)
    if re.search(r'备考|模拟合并|模拟财务', title):
        return {'periods': [], 'evidence': [], 'excluded': 'pro_forma_or_simulated_accounts'}
    issuer = re.sub(r'^\*?ST|^退市', '', normalized(issuer_name), flags=re.IGNORECASE)
    aliases = [name for name in (issuer, normalized(issuer_full_name or '')) if len(name) >= 2]
    if not aliases:
        return {'periods': [], 'evidence': [], 'reason': 'issuer_name_not_available'}
    issuer_pages = [page['page'] for page in pages if any(name in normalized(page['text'])[:700] for name in aliases)
                    and re.search(r'我们(?:审计|审阅)了|编制单位', normalized(page['text'])[:700])]
    issuer_title = any(name in title for name in aliases) or '发行人' in title or '关于公司首次公开发行' in title
    evidence = []
    for page in pages:
        text = normalized(page['text'])
        # Use statement headings or the auditor's description of the accounts, not dated footnotes.
        heading = r'(?:合并|母公司)?(?:资产负债表|利润表|现金流量表)(?:[（(]续[）)])?'
        heading_lines = [normalized(line) for line in page['text'].splitlines() if re.fullmatch(heading, normalized(line))]
        inline = re.search(r'^.{0,80}?('+heading+r')(?=20\d{2}年|编制单位|$)', text)
        heading_index = text.find(heading_lines[0]) if heading_lines else inline.start(1) if inline else None
        statement = heading_index is not None
        audit = re.search(r'我们(?:审计|审阅)了', text[:600])
        if not statement and not audit:
            continue
        if statement:
            assert heading_index is not None
            scope = text[max(0, heading_index-80):heading_index+600]
        else:
            assert audit is not None
            scope = text[audit.start():audit.start()+650]
        preparer = re.search(r'编制单位[:：]?([^\d]{2,60}?公司)', scope)
        if preparer and not any(name in preparer[1] for name in aliases):
            continue
        basis = 'page_issuer_name'
        if not any(name in scope for name in aliases):
            if not (statement and issuer_pages and issuer_title):
                continue
            # A stamp can obscure the preparer on a statement page. Keep only its header dates
            # after the same document independently names the issuer in its audit scope.
            assert heading_index is not None
            scope, basis = text[heading_index:heading_index+180], 'issuer_title_and_document_audit'
        if re.search(r'备考|模拟合并|模拟财务', scope):
            continue
        found = set()
        for year, month, day in re.findall(r'(20\d{2})年(\d{1,2})月(\d{1,2})日', scope):
            try:
                date = dt.date(int(year), int(month), int(day))
            except ValueError:
                continue
            if (date.month, date.day) in {(3, 31), (6, 30), (9, 30), (12, 31)}:
                found.add(date)
        for year, month in re.findall(r'(20\d{2})年1月?(?:-|至|—|一|~)(3|6|9|12)月', scope):
            m = int(month)
            found.add(dt.date(int(year), m, 31 if m in (3, 12) else 30))
        for year in re.findall(r'(20\d{2})年度', scope):
            found.add(dt.date(int(year), 12, 31))
        for period in sorted(day for day in found if day <= published):
            evidence.append({'page': page['page'], 'period': str(period), 'text': scope,
                             'issuer_basis': basis, 'issuer_context_pages': issuer_pages,
                             'audit_scope': bool(audit and not statement)})
    candidates = sorted({row['period'] for row in evidence})
    periods = [period for period in candidates if
               len({row['page'] for row in evidence if row['period'] == period}) >= 2 or
               any(row['audit_scope'] for row in evidence if row['period'] == period)]
    unconfirmed = [row for row in evidence if row['period'] not in periods]
    evidence = [row for row in evidence if row['period'] in periods]
    return {'periods': periods, 'evidence': evidence, 'unconfirmed_evidence': unconfirmed,
            'reason': None if periods else 'no_readable_issuer_statement_period',
            'scope': 'Only explicitly recognized dates in issuer statement or audit headers'}
