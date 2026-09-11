"""Read the public HKEX aggregate southbound holdings search and retain its date."""
import datetime as dt
import html
import re
from html.parser import HTMLParser

import httpx
import polars as pl

URL = 'https://www3.hkexnews.hk/sdw/search/mutualmarket.aspx?t=hk'


class FormInputs(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.fields: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == 'input' and values.get('name'):
            self.fields[str(values['name'])] = values.get('value') or ''


def parse_holdings(page: str, *, expected_date: dt.date | None = None) -> pl.DataFrame:
    match = re.search(r'Shareholding Date:\s*(\d{4}/\d{2}/\d{2})\s*</span>', page)
    if match is None:
        raise ValueError('HKEX result date missing')
    date = dt.datetime.strptime(match[1], '%Y/%m/%d').date()
    if expected_date is not None and date != expected_date:
        raise ValueError('HKEX returned a different shareholding date')
    rows = []
    for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>', page, re.S):
        if not re.search(r'<td\b[^>]*class="col-stock-code"', row):
            continue
        cells = re.findall(r'<div class="mobile-list-body">(.*?)</div>', row, re.S)
        if len(cells) != 4:
            raise ValueError('HKEX holdings schema changed')
        values = [html.unescape(re.sub(r'<[^>]+>', '', value)).strip() for value in cells]
        code, name, shares, percent = values
        if not re.fullmatch(r'\d{1,5}', code):
            raise ValueError('Invalid HKEX security code')
        quantity = int(shares.replace(',', ''))
        ratio = float(percent.removesuffix('%')) if percent else None
        if quantity < 0 or (ratio is not None and not 0 <= ratio <= 100):
            raise ValueError('Invalid HKEX holding values')
        rows.append({'symbol': f'{int(code):05d}.HK', 'shareholding_date': date,
                     'name': name, 'shares': quantity, 'issued_share_percent': ratio})
    if not rows:
        raise ValueError('HKEX returned no holdings')
    result = pl.from_dicts(rows)
    if result['symbol'].is_duplicated().any():
        raise ValueError('Duplicate HKEX security')
    return result


def fetch_holdings(date: dt.date | None = None) -> tuple[str, pl.DataFrame]:
    with httpx.Client(timeout=40, headers={'User-Agent': 'Mozilla/5.0'}) as client:
        response = client.get(URL)
        response.raise_for_status()
        if date is not None:
            inputs = FormInputs()
            inputs.feed(response.text)
            response = client.post(URL, data={**inputs.fields, '__EVENTTARGET': 'btnSearch',
                '__EVENTARGUMENT': '', 'txtShareholdingDate': date.strftime('%Y/%m/%d')})
            response.raise_for_status()
        return response.text, parse_holdings(response.text, expected_date=date)
