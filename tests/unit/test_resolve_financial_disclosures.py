import json
import subprocess

import polars as pl

from quant.data import resolve_financial_disclosures as resolver
from quant.data.connectors.cninfo_announcements import AnnouncementDocumentTooLarge


def test_resolution_preserves_raw_and_adds_only_recognized_issuer_periods(tmp_path, monkeypatch):
    raw = tmp_path/'announcements.parquet'
    pl.DataFrame({'announcementId': ['1', '2', '3'], 'secName': ['金道科技']*3,
                  'adjunctUrl': ['finalpage/2026-09-10/'+str(i)+'.PDF' for i in (1, 2, 3)]}).write_parquet(raw)
    later = tmp_path/'later.parquet'
    pl.DataFrame({'announcementId': ['4'], 'id': [42], 'secName': ['金道科技'],
                  'adjunctUrl': ['finalpage/2026-09-10/4.PDF']}).write_parquet(later)
    source = tmp_path/'source'
    source.mkdir()
    original = {'start': '2026-09-10', 'end': '2026-09-10', 'raw_paths': [str(raw), str(later)],
        'requests': [{'symbol': '301279.SZ', 'period': '2026-06-30'}], 'unresolved': [
            {'symbol': '301279.SZ', 'announcement_id': str(i), 'announcement_date': '2026-09-10',
             'title': title, 'reason': 'report_period_not_explicit_in_title'} for i, title in
            ((1, '发行人最近一期财务报告'), (2, '模拟合并财务报表'), (3, '财务报告'))]}
    (source/'summary.json').write_text(json.dumps(original), encoding='utf-8')
    calls = []
    monkeypatch.setattr(resolver, 'issuer_names', lambda *args, **kwargs: {'301279.SZ': {'fullname': '金道科技股份有限公司'}})
    monkeypatch.setattr(resolver, 'download_document', lambda path: b'%PDF-fixture')

    def ocr(pdf, output):
        calls.append(pdf)
        if pdf.stem == '3':
            raise RuntimeError('OCR unavailable')
        return [{'page': page, 'text': '合并资产负债表 编制单位：金道科技 2025年12月31日 2026年6月30日'} for page in (1, 2)]

    monkeypatch.setattr(resolver, 'ocr_pages', ocr)
    kwargs = dict(disclosures=source, data_root=tmp_path/'data', output=tmp_path/'resolved',
                  document_cache=tmp_path/'cache')
    result = resolver.resolve(**kwargs)
    assert result['requests'] == [{'symbol': '301279.SZ', 'period': p} for p in ('2025-12-31', '2026-06-30')]
    assert len(result['document_resolutions']) == 1 and len(result['excluded_documents']) == 1
    assert result['unresolved'][0]['reason'] == 'document_text_unavailable'
    assert len(calls) == 2 and all(path.read_bytes() == b'%PDF-fixture' for path in calls)
    assert resolver.resolve(**kwargs) == result and len(calls) == 2
    assert json.loads((source/'summary.json').read_text()) == original
    assert '2025-12-31' in (tmp_path/'resolved'/'report.md').read_text(encoding='utf-8')


def test_ocr_resume_requests_only_missing_pages(tmp_path, monkeypatch):
    monkeypatch.setattr(resolver.shutil, 'which', lambda name: name)
    output = tmp_path/'ocr'
    output.mkdir()
    first = json.dumps({'page': 1, 'text': 'already inspected'})+'\n'
    (output/'pages.jsonl').write_text(first, encoding='utf-8')
    calls = []

    def run(args, **kwargs):
        calls.append(args[0])
        if args[0] == 'pdfinfo':
            return subprocess.CompletedProcess(args, 0, stdout='Pages: 2\n')
        if args[0] == 'pdftoppm':
            for n in (1, 2):
                (output/'images'/f'page-{n}.png').write_bytes(b'image')
        else:
            request = json.loads((output/'input_pages.json').read_text())
            assert [row['page'] for row in request] == [2]
            with (output/'pages.jsonl').open('a', encoding='utf-8') as file:
                file.write(json.dumps({'page': 2, 'text': 'new page'})+'\n')
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(resolver.subprocess, 'run', run)
    result = resolver.ocr_pages(tmp_path/'raw.pdf', output)
    assert len(result) == 2 and calls == ['pdfinfo', 'pdftoppm', 'powershell.exe']
    assert (output/'pages.jsonl').read_text().startswith(first)
    assert resolver.ocr_pages(tmp_path/'raw.pdf', output) == result
    assert calls[-1] == 'pdfinfo' and len(calls) == 4


def test_exact_full_name_metadata_is_preserved_and_reused(tmp_path, monkeypatch):
    calls = []

    class Client:
        def __init__(self, **kwargs):
            pass

        def query_raw(self, name, **kwargs):
            calls.append(kwargs['ts_code'])
            return pl.DataFrame({'ts_code': [kwargs['ts_code']], 'name': ['百邦科技'],
                                 'fullname': ['北京百华悦邦科技股份有限公司']})

    monkeypatch.setattr(resolver, 'TushareConnector', Client)
    monkeypatch.setattr(resolver.time, 'sleep', lambda seconds: None)
    kwargs = dict(data_root=tmp_path/'data', output=tmp_path/'out')
    names = resolver.issuer_names(['300736.SZ'], **kwargs)
    assert names['300736.SZ']['fullname'] == '北京百华悦邦科技股份有限公司'
    assert resolver.issuer_names(['300736.SZ'], **kwargs) == names and calls == ['300736.SZ']


def test_partial_document_preserves_unknown_dates_without_requesting_them(tmp_path, monkeypatch):
    raw = tmp_path/'announcements.parquet'
    pl.DataFrame({'announcementId': ['1'], 'secName': ['金道科技'],
                  'adjunctUrl': ['finalpage/2026-09-10/1.PDF']}).write_parquet(raw)
    source = tmp_path/'source'
    source.mkdir()
    (source/'summary.json').write_text(json.dumps({'start': '2026-09-10', 'end': '2026-09-10',
        'raw_paths': [str(raw)], 'requests': [], 'unresolved': [{'symbol': '301279.SZ',
        'announcement_id': '1', 'announcement_date': '2026-09-10', 'title': '发行人最近一年一期财务报告',
        'reason': 'report_period_not_explicit_in_title'}]}), encoding='utf-8')
    monkeypatch.setattr(resolver, 'issuer_names', lambda *a, **k: {'301279.SZ': {'fullname': None}})
    monkeypatch.setattr(resolver, 'download_document', lambda path: b'%PDF-fixture')
    monkeypatch.setattr(resolver, 'ocr_pages', lambda *a: [
        {'page': 1, 'text': '我们审计了金道科技2025年度财务报表'},
        {'page': 111, 'text': '母公司现金流量表\n2021年度'}])
    result = resolver.resolve(disclosures=source, data_root=tmp_path/'data',
                              output=tmp_path/'out', document_cache=tmp_path/'cache')
    assert result['requests'] == [{'symbol': '301279.SZ', 'period': '2025-12-31'}]
    assert len(result['document_resolutions']) == 1
    assert result['unresolved'][0]['reason'] == 'partially_readable_document_periods'
    assert result['unresolved'][0]['unconfirmed_evidence'][0]['period'] == '2021-12-31'


def test_oversized_announcement_pdf_is_unresolved_without_aborting_batch(tmp_path, monkeypatch):
    raw = tmp_path/'announcements.parquet'
    pl.DataFrame({'announcementId': ['1', '2'], 'secName': ['金道科技', '金道科技'],
                  'adjunctUrl': ['finalpage/2026-09-10/1.PDF', 'finalpage/2026-09-10/2.PDF']
                  }).write_parquet(raw)
    source = tmp_path/'source'
    source.mkdir()
    (source/'summary.json').write_text(json.dumps({
        'start': '2026-09-10', 'end': '2026-09-10', 'raw_paths': [str(raw)], 'requests': [],
        'unresolved': [
            {'symbol': '301279.SZ', 'announcement_id': '1', 'announcement_date': '2026-09-10',
             'title': '发行人最近一期财务报告', 'reason': 'report_period_not_explicit_in_title'},
            {'symbol': '301279.SZ', 'announcement_id': '2', 'announcement_date': '2026-09-10',
             'title': '发行人最近一期财务报告', 'reason': 'report_period_not_explicit_in_title'},
        ],
    }), encoding='utf-8')

    def download(path):
        if path.endswith('/1.PDF'):
            raise AnnouncementDocumentTooLarge('Announcement document exceeds the 128 MiB limit')
        return b'%PDF-fixture'

    monkeypatch.setattr(resolver, 'issuer_names',
                        lambda *a, **k: {'301279.SZ': {'fullname': '金道科技股份有限公司'}})
    monkeypatch.setattr(resolver, 'download_document', download)
    monkeypatch.setattr(resolver, 'ocr_pages', lambda *a: [
        {'page': page, 'text': '合并资产负债表 编制单位：金道科技 2025年12月31日 2026年6月30日'}
        for page in (1, 2)])
    result = resolver.resolve(disclosures=source, data_root=tmp_path/'data',
                              output=tmp_path/'out', document_cache=tmp_path/'cache')
    assert result['requests'] == [
        {'symbol': '301279.SZ', 'period': '2025-12-31'},
        {'symbol': '301279.SZ', 'period': '2026-06-30'},
    ]
    assert len(result['document_resolutions']) == 1
    assert result['document_resolutions'][0]['announcement_id'] == '2'
    oversized = [row for row in result['unresolved'] if row['announcement_id'] == '1']
    assert len(oversized) == 1
    assert oversized[0]['reason'] == 'document_exceeds_size_limit'
    assert '128 MiB' in oversized[0]['detail']
    assert not list((tmp_path/'data'/'raw'/'cninfo'/'financial_disclosure_documents').rglob('1.pdf'))
